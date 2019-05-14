# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import cStringIO
import collections

from . import StreamEngine
from .annotator import AnnotatorStreamEngine


class _NopFile(object):
  # pylint: disable=multiple-statements,missing-docstring
  def write(self, data): pass
  def flush(self): pass


class _NopLogStream(StreamEngine.Stream):
  # pylint: disable=multiple-statements
  def write_line(self, line): pass
  def close(self): pass


class _NopStepStream(AnnotatorStreamEngine.StepStream):
  def __init__(self, engine, step_name):
    super(_NopStepStream, self).__init__(engine, _NopFile(), step_name)

  def new_log_stream(self, _):
    return _NopLogStream()

  def close(self):
    pass


class _SimulationStepStream(AnnotatorStreamEngine.StepStream):
  # We override annotations we don't want to show up in followup_annotations
  def new_log_stream(self, log_name):
    # We sink 'execution details' to dev/null. This is the log that the recipe
    # engine produces that contains the printout of the command, environment,
    # etc.
    #
    # The '$debug' log is conditionally filtered in _merge_presentation_updates.
    if log_name in ('execution details',):
      return _NopLogStream()
    return super(_SimulationStepStream, self).new_log_stream(log_name)

  def trigger(self, spec):
    pass

  def close(self):
    pass


class SimulationAnnotatorStreamEngine(AnnotatorStreamEngine):
  """Stream engine which just records generated commands."""

  def __init__(self):
    self._step_buffer_map = collections.OrderedDict()
    super(SimulationAnnotatorStreamEngine, self).__init__(
        self._step_buffer(None))

  @property
  def buffered_steps(self):
    """Returns an OrderedDict of all steps run by dot-name to a cStringIO
    buffer with any annotations printed."""
    return self._step_buffer_map

  def _step_buffer(self, step_name):
    return self._step_buffer_map.setdefault(step_name, cStringIO.StringIO())

  def new_step_stream(self, step_config):
    # TODO(iannucci): don't skip these. Omitting them for now to reduce the
    # amount of test expectation changes.
    steps_to_skip = (
      'recipe result',   # explicitly covered by '$result'
    )
    if step_config.name in steps_to_skip:
      return _NopStepStream(self, step_config.name)

    stream = _SimulationStepStream(
        self, self._step_buffer(step_config.name), step_config.name)
    # TODO(iannucci): this is duplicated with
    # AnnotatorStreamEngine._create_step_stream
    if len(step_config.name_tokens) > 1:
      # Emit our current nest level, if we are nested.
      stream.output_annotation(
          'STEP_NEST_LEVEL', str(len(step_config.name_tokens)-1))
    return stream
