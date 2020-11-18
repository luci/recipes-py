# -*- coding: utf-8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import logging
import traceback

import attr
import gevent

from google.protobuf import json_format as jsonpb
from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from google.protobuf.struct_pb2 import Struct

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.step import Step
from PB.go.chromium.org.luci.buildbucket.proto import common

from ...recipe_api import InfraFailure, StepFailure
from ...third_party import logdog

from ..attr_util import attr_type

from . import StreamEngine


LOG = logging.getLogger(__name__)


@attr.s
class LUCIStepMarkdownWriter(object):
  _step_text = attr.ib(default='')
  def add_step_text(self, text):
    self._step_text += text

  _step_summary_text = attr.ib(default='')
  def add_step_summary_text(self, text):
    self._step_summary_text += text

  _step_links = attr.ib(factory=list)
  def add_step_link(self, linkname, link):
    self._step_links.append((linkname, link))

  def render(self):
    escape_parens = lambda link: link.replace('(', r'\(').replace(')', r'\)')

    paragraphs = []

    if self._step_summary_text:
      paragraphs.append(self._step_summary_text)

    if self._step_text:
      paragraphs.append(self._step_text)

    if self._step_links:
      paragraphs.append(
          '\n'.join(
              '  * [%s](%s)' % (name, escape_parens(link))
              for name, link in self._step_links))

    return '\n\n'.join(paragraphs)


@attr.s
class LUCILogStream(StreamEngine.Stream):
  """Implementation of StreamEngine.Stream for luciexe mode.

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
  """Implementation of StreamEngine.StepStream for luciexe mode.

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
  _tags = attr.ib(validator=attr_type(RepeatedCompositeFieldContainer))
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
  #
  # stdhandle is a single handle which will either point to stdout or stderr. In
  # the case where the step is using logdog for stdout and stderr, they're
  # currently merged together because people are used to seeing the output
  # interleaved.
  #
  # TODO(iannucci) Once logdog/resultdb supports viewing muxed streams again,
  # separate stdout and stderr into separate streams.
  _std_handle = attr.ib(default=None)
  _logging = attr.ib(default=None)

  # If True, after initialization, append a log named '$build.proto' that
  # points to the 'build.proto' stream of the luciexe this step launches.
  # Host application will treat this step as merge step according to luciexe
  # protocol.
  #
  # See: [luciexe recursive invocation](https://pkg.go.dev/go.chromium.org/luci/luciexe?tab=doc#hdr-Recursive_Invocation)
  _merge_step = attr.ib(default=False, validator=attr_type(bool))

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

  def __attrs_post_init__(self):
    self._stream_namespace = logdog.streamname.normalize(
      self._step.name.replace('|', '/'), 'l')

    if self._merge_step:
      stream_name = '/'.join((self._stream_namespace, 'u', 'build.proto'))
      if stream_name in self._CREATED_LOGS:
        raise ValueError("Duplicated build.proto stream %s" % (stream_name,))
      self._CREATED_LOGS.add(stream_name)

      log = self._step.logs.add()
      log.name = '$build.proto'
      log.url = stream_name
      self._change_cb()

  def new_log_stream(self, log_name):
    """Add a new log with name `log_name` to this step.

    Will mangle `log_name` to produce a valid and non-conflicting logdog stream
    name.

    Returns file-like text stream object. This file-like object includes
    fileno() and so is suitable for use with subprocess IO redirection."""
    try:
      if log_name == 'logging':
        logstream = self.logging
        if logstream.closed:
          raise ValueError('Attempting to open closed logstream %r' % log_name)
        return logstream

      return self._new_log_stream(log_name)
    except:
      LOG.exception('new_log_stream %r: %r', self._step.name, log_name)
      raise

  def _new_log_stream(self, log_name):
    dedup_idx = 0
    base_flattened_name = '/'.join(
      (self._stream_namespace, logdog.streamname.normalize(log_name, 'l')))
    flat_name = base_flattened_name
    while flat_name in self._CREATED_LOGS:
      flat_name = logdog.streamname.normalize(
          base_flattened_name + ('_%d' % dedup_idx), 'l')
      dedup_idx += 1

    log_stream = self._bsc.open_text(flat_name)
    self._CREATED_LOGS.add(flat_name)

    log = self._step.logs.add()
    log.name = log_name
    log.url = flat_name
    self._change_cb()
    return LUCILogStream(log_stream)

  def append_log(self, log):
    self._step.logs.add().CopyFrom(log)
    self._change_cb()

  def mark_running(self):
    if self._step.status == common.SCHEDULED:
      self._step.summary_markdown = ""
      self._step.status = common.STARTED
      self._step.start_time.GetCurrentTime()
      self._change_cb()

  def set_summary_markdown(self, text):
    self._step.summary_markdown = text
    self._change_cb()

  def add_step_text(self, text):
    self._back_compat_markdown.add_step_text(text)

  def add_step_summary_text(self, text):
    self._back_compat_markdown.add_step_summary_text(text)

  def add_step_link(self, name, url):
    self._back_compat_markdown.add_step_link(name, url)

  def set_step_status(self, status, had_timeout):
    _ = had_timeout
    self._step.status = {
      'SUCCESS': common.SUCCESS,
      'FAILURE': common.FAILURE,
      'WARNING': common.SUCCESS, # TODO(iannucci): support WARNING
      'EXCEPTION': common.INFRA_FAILURE,
    }[status]
    # TODO(iannucci): set timeout bit here

  def set_build_property(self, key, value):
    # Intercept tags
    if key == '$recipe_engine/buildbucket/runtime-tags':
      for k, vals in json.loads(value).iteritems():
        self._tags.extend([common.StringPair(key=k, value=v) for v in set(vals)
            if common.StringPair(key=k, value=v) not in self._tags])
      return

    self._properties[key] = json.loads(value)

  @property
  def logging(self):
    """Returns an open text stream for this step's logging stream."""
    if not self._logging:
      self._logging = self._new_log_stream('logging')
    return self._logging

  def open_std_handles(self, stdout=False, stderr=False):
    if self._std_handle is not None:
      LOG.exception('open_std_handles called twice: %r', self._step.name)
      raise ValueError(
          'open_std_handles may only be called once: %r', self._step.name)

    ret = {}
    if not stdout and not stderr:
      return ret

    if not stdout:
      self._std_handle = self.new_log_stream('stderr')
      ret['stderr'] = self._std_handle
      return ret

    self._std_handle = self.new_log_stream('stdout')
    ret['stdout'] = self._std_handle
    if stderr:
      ret['stderr'] = self._std_handle
    return ret

  @property
  def env_vars(self):
    logdog_namespace = self.user_namespace
    if self._bsc.namespace:
      logdog_namespace = '/'.join((self._bsc.namespace, logdog_namespace))
    return {'LOGDOG_NAMESPACE': logdog_namespace}

  @property
  def user_namespace(self):
    return '/'.join((self._stream_namespace, 'u'))

  def write_line(self, line):
    """Differs from our @@@annotator@@@ bretheren and puts logging data to
    an independent stream."""
    # TODO(iannucci): have step_runner log the step metadata as a protobuf
    # and/or put it in the Step proto message.
    return self.logging.write_line(line)

  def close(self):
    # TODO(iannucci): close ALL log streams, not just stdout/stderr/logging
    # TODO(iannucci): this can actually double-close with subprocess runner...
    # clean all of this up once annotations are gone.
    if self._std_handle:
      self._std_handle.close()
    # TODO(iannucci): improve UI modification interface to immediately send UI
    # changes when they happen.
    self._step.end_time.GetCurrentTime()
    self._step.summary_markdown = self._back_compat_markdown.render()
    if self._step.status == common.STARTED:
      self._step.status = common.SUCCESS
    self._change_cb()


@attr.s
class LUCIStreamEngine(StreamEngine):
  """Implementation of StreamEngine for luciexe mode.

  Holds a LogDog datagram stream for Build messages and manages writes to this
  stream.
  """

  # This causes the 'build.proto' datagram stream to export as JSONPB instead of
  # Binary PB. Only used for debugging. `luciexe` protocol does not support
  # JSONPB.
  _export_build_as_json = attr.ib(validator=attr_type(bool))

  # The current Build message. This is mutated and then sent with the _send
  # function (seen as _change_cb in other classes in this file).
  _build_proto = attr.ib(factory=lambda: Build(status=common.STARTED))

  # The Butler StreamClient. Used to generate logs for individual steps.
  _bsc = attr.ib(
      validator=attr_type(logdog.stream.StreamClient),
      factory=lambda: logdog.bootstrap.ButlerBootstrap.probe().stream_client(),
  )

  # The Build message datagram stream.
  _build_stream = attr.ib()
  @_build_stream.default
  def _build_stream_default(self):
    content_enc = 'jsonpb' if self._export_build_as_json else 'proto'
    content_type = 'application/luci+%s; message=buildbucket.v2.Build' % (
          content_enc,)
    if content_enc == 'proto':
      content_type += '; encoding=zlib'
    return self._bsc.open_datagram('build.proto', content_type=content_type)

  _send_event = attr.ib(default=gevent.event.Event())
  _sender_die = attr.ib(default=False)

  _sender = attr.ib()
  @_sender.default
  def _sender_default(self):
    def _do_send():
      self._build_stream.send(
          jsonpb.MessageToJson(self._build_proto,
                               preserving_proto_field_name=True)
          if self._export_build_as_json else
          self._build_proto.SerializeToString().encode('zlib')
      )

    def _send_fn():
      while not self._sender_die:
        # wait until SOMEONE wants to send something.
        self._send_event.wait()
        if self._sender_die:
          break

        # Then wait for a second, in case other updates come in.
        gevent.sleep(1)

        # atomically:
        #   clear the event
        #   serialize the current build proto state (part of _do_send)
        # then send the serialized data asynchronously.
        self._send_event.clear()
        _do_send()

      # One last send before exiting to make sure all build updates are
      # sent to logdog
      _do_send()

    return gevent.spawn(_send_fn)

  def _send(self):
    self._send_event.set()

  def new_step_stream(self, name_tokens, allow_subannotations,
                      merge_step=False):
    assert not allow_subannotations, (
      'Subannotations not currently supported in build.proto mode'
    )
    step_pb = self._build_proto.steps.add(
        name='|'.join(name_tokens),
        status=common.SCHEDULED)

    ret = LUCIStepStream(step_pb, self._build_proto.output.properties,
                         self._build_proto.tags, self._send, self._bsc,
                         merge_step=merge_step)
    self._send()
    return ret

  def close(self):
    self._sender_die = True
    self._send()
    self._sender.join()
    self._build_stream.close()

  @property
  def supports_concurrency(self):
    return True

  def write_result(self, result):
    self._build_proto.status = result.status
    self._build_proto.summary_markdown = result.summary_markdown
    self._send()

  @property
  def current_build_proto(self):
    """Returns the current Build message.

    Note: Any update on the returned build before engine closes will be
    sent to `build.proto` stream
    """
    return self._build_proto

  @property
  def was_successful(self):
    """Used by luciexe to set the recipe engine's returncode.

    This isn't strictly necessary, but it can be helpful for debugging.
    """
    return self._build_proto.status == common.SUCCESS
