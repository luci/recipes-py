# -*- coding: utf8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import logging
import json

import attr

from google.protobuf import json_format as jsonpb
from google.protobuf.struct_pb2 import Struct

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.step import Step
from PB.go.chromium.org.luci.buildbucket.proto import common

from ....recipe_api import StepClient, InfraFailure
from ....third_party import logdog

from ...stream import StreamEngine
from ...attr_util import attr_type

from .markdown_writer import LUCIStepMarkdownWriter


LOG = logging.getLogger(__name__)


@attr.s
class LUCILogStream(StreamEngine.Stream):
  """Implementation of StreamEngine.Stream for the run_build execution engine.

  It's a very thin wrapper around a LogDog text stream."""

  # pylint: disable=protected-access
  _stream = attr.ib(validator=attr_type(
      (type(None), logdog.stream.StreamClient._BasicStream)))

  def fileno(self):
    """Returns underlying logdog file descriptor.

    Used by subprocess.Popen when redirecting a subprocess output to this
    stream.
    """
    return self._stream.fileno()

  def write_line(self, line):
    """Writes a single line to the underlying stream."""
    self._stream.write(line + '\n')

  def close(self):
    """Closes the stream. No more writes allowed by the current process."""
    if self.closed:
      return
    self._stream.close()
    self._stream = None

  @property
  def closed(self):
    """Returns True if the stream has been closed."""
    return self._stream is None


@attr.s
class LUCIStepStream(StreamEngine.StepStream):
  """Implementation of StreamEngine.StepStream for the run_build execution
  engine.

  Holds a stdout and stderr file (opened lazily), as well as a Step protobuf
  message which is part of this execution's Build message.

  Has a ref to the global Build.output.properties field.

  Presentation changes alters either the Step or the properties and calls
  a global callback to write these changes to the logdog Build proto stream
  (owned by the LUCIStreamEngine).

  Handles uniqification of all logdog stream names in this process.
  """
  _step = attr.ib(validator=attr_type(Step))
  _properties = attr.ib(validator=attr_type(Struct))
  # change_cb is a void function which causes the LUCIStreamEngine to emit the
  # current Build proto message. This must be called after any changes to:
  #   * self._step
  #   * self._properties
  #
  # TODO(iannucci): change _change_cb to a context-manager for step, i.e.
  #   with self._step as pb:
  #      # tweak pb
  _change_cb = attr.ib()

  # The Butler StreamClient. Used to generate logs for individual steps.
  _bsc = attr.ib(validator=attr_type(logdog.stream.StreamClient))

  # File-like objects for stdout/stderr (logdog streams).
  _stdout = attr.ib(default=None)
  _stderr = attr.ib(default=None)
  _logging = attr.ib(default=None)

  _back_compat_markdown = attr.ib(factory=LUCIStepMarkdownWriter)

  # A global set of created logdog stream names for all steps. Used to
  # deduplicate log stream names, since the logdog stream name alphabet is
  # a subset of the alphabet allowed for log names in build.proto.
  #
  # Contains the entire logstream name as seen by logdog (e.g.
  # parent/child/logname). This is because we need to deduplicate log streams as
  # logdog sees them (i.e. after we've 'normalized' whatever real name the user
  # has given us for the stream). As long as the user gives us non-exotic names,
  # these will be generally readable. If the user gives us junk with e.g. emoji,
  # we may see conflicts (since multiple parents and steps may normalize to the
  # same logdog stream name).
  #
  # TODO(iannucci): deduplicate hierarchically so that "💩 step" and "🎉 step"
  # will do their deduplication at the step level, rather than at the leaf log
  # level. e.g. right now we'll end up with:
  #
  #   l___step/stdout     "💩 step/stdout"
  #   l___step/stderr     "💩 step/stderr"
  #   l___step/stdout_0   "🎉 step/stdout"
  #   l___step/stderr_0   "🎉 step/stderr"
  #   l___step/stdout_1   "🍔 step/stdout"
  #   l___step/stderr_1   "🍔 step/stderr"
  #
  # But we should really have:
  #
  #   l___step/stdout     "💩 step/stdout"
  #   l___step/stderr     "💩 step/stderr"
  #   l___step_0/stdout   "🎉 step/stdout"
  #   l___step_0/stderr   "🎉 step/stderr"
  #   l___step_1/stdout   "🍔 step/stdout"
  #   l___step_1/stderr   "🍔 step/stderr"
  _CREATED_LOGS = set()

  def new_log_stream(self, log_name):
    """Add a new log with name `log_name` to this step.

    Will mangle `log_name` to produce a valid and non-conflicting logdog stream
    name.

    Returns file-like text stream object. This file-like object includes
    fileno() and so is suitable for use with subprocess IO redirection."""
    try:
      if log_name in ('stdout', 'stderr', 'logging'):
        stdlog = getattr(self, log_name)
        if stdlog.closed:
          raise ValueError('Attempting to open closed logstream %r' % log_name)
        return stdlog

      return self._new_log_stream(log_name)
    except:
      LOG.exception('new_log_stream %r: %r', self._step.name, log_name)
      raise

  def _new_log_stream(self, log_name):
    dedup_idx = 0
    base_flattened_name = logdog.streamname.normalize(
        self._step.name.replace('|', '/') + '/' + log_name, 'l')
    flat_name = base_flattened_name
    while flat_name in self._CREATED_LOGS:
      flat_name = logdog.streamname.normalize(
          base_flattened_name + ('_%d' % dedup_idx), 'l')
      dedup_idx += 1

    log_stream = self._bsc.open_text(flat_name)
    self._CREATED_LOGS.add(flat_name)

    log = self._step.logs.add()
    log.name = log_name
    log.view_url = log_stream.get_viewer_url()
    log.url = 'logdog://%s/%s/%s' % (
      self._bsc.coordinator_host,
      self._bsc.project,
      log_stream.path
    )
    self._change_cb()
    return LUCILogStream(log_stream)

  def add_step_text(self, text):
    self._back_compat_markdown.add_step_text(text)

  def add_step_summary_text(self, text):
    self._back_compat_markdown.add_step_summary_text(text)

  def add_step_link(self, name, url):
    self._back_compat_markdown.add_step_link(name, url)

  def set_manifest_link(self, name, sha256, url):
    raise NotImplementedError(
        'run_build does not support manifest links yet. If you encounter this '
        'please talk to the luci-dev folks. When this is supported on '
        'run_build it will be via direct manifest embedding')

  def set_step_status(self, status):
    self._step.status = {
      'SUCCESS': common.SUCCESS,
      'FAILURE': common.FAILURE,
      'WARNING': common.FAILURE, # TODO(iannucci): support WARNING
      'EXCEPTION': common.INFRA_FAILURE,
    }[status]

  def set_build_property(self, key, value):
    self._properties[key] = json.loads(value)

  @property
  def stdout(self):
    """Returns an open text stream for this step's stdout."""
    if not self._stdout:
      self._stdout = self._new_log_stream('stdout')
    return self._stdout

  @property
  def logging(self):
    """Returns an open text stream for this step's logging stream."""
    if not self._logging:
      self._logging = self._new_log_stream('logging')
    return self._logging

  @property
  def stderr(self):
    """Returns an open text stream for this step's stderr."""
    if not self._stderr:
      self._stderr = self._new_log_stream('stderr')
    return self._stderr

  def write_line(self, line):
    """Differs from our @@@annotator@@@ bretheren and puts logging data to
    an independent stream."""
    # TODO(iannucci): have step_runner log the step metadata as a protobuf
    # and/or put it in the Step proto message.
    return self.logging.write_line(line)

  def close(self):
    if self._stdout:
      self._stdout.close()
    if self._stderr:
      self._stderr.close()
    # TODO(iannucci): improve UI modification interface to immediately send UI
    # changes when they happen.
    self._step.end_time.GetCurrentTime()
    self._step.summary_markdown = self._back_compat_markdown.render()
    self._change_cb()


@attr.s
class LUCIStreamEngine(StreamEngine):
  """Implementation of StreamEngine for the run_build execution engine.

  Holds a LogDog datagram stream for Build messages and manages writes to this
  stream.
  """

  # This causes the 'build.proto' datagram stream to export as JSONPB instead of
  # Binary PB. Only used for debugging. `run_build` protocol does not support
  # JSONPB.
  _export_build_as_json = attr.ib(validator=attr_type(bool))

  # The current Build message. This is mutated and then sent with the _send
  # function (seen as _change_cb in other classes in this file).
  _build_proto = attr.ib(factory=Build)

  # The Butler StreamClient. Used to generate logs for individual steps.
  _bsc = attr.ib(
      validator=attr_type(logdog.stream.StreamClient),
      factory=lambda: logdog.bootstrap.ButlerBootstrap.probe().stream_client(),
  )

  # The Build message datagram stream.
  _build_stream = attr.ib()
  @_build_stream.default
  def _build_stream_default(self):
    content_enc = "jsonpb" if self._export_build_as_json else "proto"
    ext = '.json' if self._export_build_as_json else '.pb'
    return self._bsc.open_datagram(
        'build.proto',
        content_type='application/luci+%s; message=buildbucket.v2.Build' % (
          content_enc),
        binary_file_extension=ext)

  def _send(self):
    self._build_stream.send(
        jsonpb.MessageToJson(self._build_proto,
                             preserving_proto_field_name=True)
        if self._export_build_as_json else
        self._build_proto.SerializeToString()
    )

  def new_step_stream(self, step_config):
    assert isinstance(step_config, StepClient.StepConfig)
    assert not step_config.allow_subannotations, (
      'Subannotations not currently supported in build.proto mode'
    )
    step_pb = self._build_proto.steps.add()
    step_pb.name = '|'.join(step_config.name_tokens)
    step_pb.start_time.GetCurrentTime()
    ret = LUCIStepStream(step_pb, self._build_proto.output.properties,
                         self._send, self._bsc)
    self._send()
    return ret

  def close(self):
    # TODO(iannucci): handle recipe return value
    self._build_stream.close()

  def handle_exception(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
      self._build_proto.status = common.SUCCESS
    elif exc_type is InfraFailure:
      self._build_proto.status = common.INFRA_FAILURE
      # TODO(iannucci): add error log stream
      self._build_proto.output.summary_markdown = (
        'caught InfraFailure at top level: %r'
      ) % (exc_val,)
    # TODO(iannucci): handle timeout
    else:
      self._build_proto.status = common.FAILURE
      # TODO(iannucci): add error log stream
      self._build_proto.output.summary_markdown = (
        'caught Exception at top level: %r'
      ) % (exc_val,)
    self._send()

    return True

  @property
  def was_successful(self):
    """Used by run_build to set the recipe engine's returncode."""
    return self._build_proto.status == common.SUCCESS
