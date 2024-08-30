# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import json

from google.protobuf import json_format as jsonpb

from . import StreamEngine, encode_str
from ..test.empty_log import EMPTY_LOG
from ...engine_types import StepPresentation


def _ignoreable(f):
  def check_annotations(self, *args, **kwargs):
    if self._annotations is not None:
      f(self, *args, **kwargs)
  return check_annotations


class _SimulationStepStream(StreamEngine.StepStream):
  def __init__(self, annotations):
    """A step stream recording annotations for simulation tests.

    Args:
      annotations - The dictionary to map annotations into. If None, annotations
          will be ignored.
    """
    super(_SimulationStepStream, self).__init__()
    self._annotations = annotations

  def _dict_annotation(self, field):
    return self._annotations.setdefault(field, collections.OrderedDict())

  @_ignoreable
  def write_line(self, line):
    self._annotations.setdefault('raw_annotations', []).append(line)

  def open_std_handles(self, stdout=False, stderr=False):
    ret = {}
    if stdout:
      ret['stdout'] = self
    if stderr:
      ret['stderr'] = self
    return ret

  def close(self):
    pass

  def new_log_stream(self, log_name):
    # We sink '$execution details' to dev/null. This is the log that the recipe
    # engine produces that contains the printout of the command, environment,
    # etc.
    #
    # The '$debug' log is conditionally filtered in _merge_presentation_updates.
    if self._annotations is None or log_name in ('$execution details',):
      lines = None
    else:
      # TODO(gbeaty) Remove this?
      log_name = log_name.replace('/', '&#x2f;')
      logs = self._dict_annotation('logs')
      lines = []

    class LogStream(StreamEngine.Stream):
      def write_line(self, line):
        if lines is not None:
          lines.append(line)

      def close(self):
        if lines is not None:
          if not lines:
            logs[log_name] = EMPTY_LOG
          else:
            logs[log_name] = '\n'.join(encode_str(l) for l in lines)

    return LogStream()

  def append_log(self, log):
    # TODO(yiwzhang): This is confusing as it is printing the log proto msg in
    # json format in followup_annotations section of the test expectation file.
    # Normally, we print the actual log content of log there (e.g. json.output
    # log). We should improve this once we remove annotator mode and make
    # simulation speak build.proto natively.
    log_stream = self.new_log_stream(log.name)
    jsonify = jsonpb.MessageToJson(log,
        preserving_proto_field_name=True, sort_keys=True)
    for line in jsonify.splitlines():
      log_stream.write_line(line.rstrip())
    log_stream.close()

  @_ignoreable
  def add_step_text(self, text):
    self._annotations['step_text'] = text

  @_ignoreable
  def add_step_summary_text(self, text):
    self._annotations['step_summary_text'] = text

  @_ignoreable
  def add_step_link(self, name, url):
    self._dict_annotation('links')[name] = url

  @_ignoreable
  def set_step_status(self, status, had_timeout):
    assert status in StepPresentation.STATUSES, (
        'Impossible status %s' % status)
    del had_timeout
    if status != 'SUCCESS':
      self._annotations['status'] = status

  @_ignoreable
  def set_build_property(self, key, value):
    self._dict_annotation('output_properties')[key] = json.loads(value)

  def set_summary_markdown(self, text):
    # TODO(iannucci): don't ignore this... Can fix this when we remove annotator
    # mode.
    pass

  def set_step_tag(self, key, value):
    self._dict_annotation('tags')[key] = value


class SimulationStreamEngine(StreamEngine):
  """Stream engine which just records generated commands."""

  def __init__(self):
    self._annotations_map = collections.OrderedDict()
    super(SimulationStreamEngine, self).__init__()

  @property
  def annotations(self):
    return self._annotations_map

  @property
  def supports_concurrency(self):
    return True

  def new_step_stream(self, name_tokens, allow_subannotations,
                      merge_step=False):
    del allow_subannotations, merge_step

    # TODO(iannucci): don't skip these. Omitting them for now to reduce the
    # amount of test expectation changes.
    steps_to_skip = (
      'recipe result',   # explicitly covered by '$result'
    )
    # TODO(iannucci): use '|' separator instead of '.'
    name = '.'.join(name_tokens)
    if name in steps_to_skip:
      annotations = None
    else:
      annotations = self._annotations_map[name] = {}
      # TODO(iannucci): this is duplicated with
      # AnnotatorStreamEngine._create_step_stream
      if len(name_tokens) > 1:
        annotations['nest_level'] = len(name_tokens) - 1
    return _SimulationStepStream(annotations)
