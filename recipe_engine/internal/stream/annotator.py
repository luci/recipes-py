# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import time

from builtins import map

from PB.recipe_engine.result import Result

from . import StreamEngine, encode_str


class AnnotatorStreamEngine(StreamEngine):
  def __init__(self, outstream, emit_timestamps=False, time_fn=None):
    self._current_step = None
    self._opened = set()
    self._outstream = outstream
    self.emit_timestamps = emit_timestamps
    self.time_fn = time_fn or time.time

    self.final_result = Result()

  def open(self):
    super().open()
    self.output_current_time()
    self.output_root_annotation('HONOR_ZERO_RETURN_CODE')

  def close(self):
    super().close()
    self.output_current_time()

  @property
  def supports_concurrency(self):
    return False

  def output_current_time(self, step=None):
    """Prints CURRENT_TIMESTAMP annotation with current time."""
    if step:
      self._step_cursor(step)
    if self.emit_timestamps:
      self.output_root_annotation('CURRENT_TIMESTAMP', self.time_fn())

  @staticmethod
  def write_annotation(outstream, *args):
    # Flush the stream before & after engine annotations, because they can
    # change which step we are talking about and this matters to buildbot.
    outstream.flush()
    outstream.write(
        '@@@' + '@'.join(map(encode_str, args)) + '@@@\n')
    outstream.flush()

  def output_root_annotation(self, *args):
    self.write_annotation(self._outstream, *args)

  def _step_cursor(self, step_name):
    if self._current_step != step_name:
      self.output_root_annotation('STEP_CURSOR', step_name)
      self._current_step = step_name
    if step_name not in self._opened:
      self.output_current_time()
      self.output_root_annotation('STEP_STARTED')
      self._opened.add(step_name)

  class StepStream(StreamEngine.StepStream):
    def __init__(self, engine, outstream, step_name):
      super().__init__()

      self._engine = engine
      self._outstream = outstream
      self._step_name = step_name

    def basic_write(self, line):
      self._engine._step_cursor(self._step_name)
      self._outstream.write(line)

    def close(self):
      self._engine.output_current_time(step=self._step_name)
      self.output_annotation('STEP_CLOSED')

    def output_annotation(self, *args):
      self._engine._step_cursor(self._step_name)
      self._engine.write_annotation(self._outstream, *args)

    def write_line(self, line):
      if line.startswith('@@@'):
        self.basic_write('!' + line + '\n')
      else:
        self.basic_write(line + '\n')

    def open_std_handles(self, stdout=False, stderr=False):
      ret = {}
      if stdout:
        ret['stdout'] = self
      if stderr:
        ret['stderr'] = self
      return ret

    def new_log_stream(self, log_name):
      return self._engine.StepLogStream(self, log_name)

    def add_step_text(self, text):
      self.output_annotation('STEP_TEXT', text)

    def add_step_summary_text(self, text):
      self.output_annotation('STEP_SUMMARY_TEXT', text)

    def add_step_link(self, name, url):
      self.output_annotation('STEP_LINK', name, url)

    def set_step_status(self, status, had_timeout):
      _ = had_timeout
      if status == 'SUCCESS':
        pass
      elif status == 'WARNING':
        self.output_annotation('STEP_WARNINGS')
      elif status == 'FAILURE':
        self.output_annotation('STEP_FAILURE')
      elif status in ('EXCEPTION', 'CANCELED'):
        self.output_annotation('STEP_EXCEPTION')
      else:
        raise Exception('Impossible status %s' % status)

    def set_build_property(self, key, value):
      self.output_annotation('SET_BUILD_PROPERTY', key, value)

    def set_step_tag(self, key, value):
      pass

  class StepLogStream(StreamEngine.Stream):
    def __init__(self, step_stream, log_name):
      self._step_stream = step_stream
      self._log_name = log_name.replace('/', '&#x2f;')

    def write_line(self, line):
      self._step_stream.output_annotation('STEP_LOG_LINE', self._log_name, line)

    def close(self):
      self._step_stream.output_annotation('STEP_LOG_END', self._log_name)


  class AllowSubannotationsStepStream(StepStream):
    def write_line(self, line):
      self.basic_write(line + '\n')

    # HACK(luqui): If the subannotator script changes the active step, we need
    # a way to get back to the real step that spawned the script.  The right
    # way to do that is to parse the annotation stream and re-emit it.  But for
    # now we just provide this method.
    def reset_subannotation_state(self):
      self._engine._current_step = None

  def new_step_stream(self,
                      name_tokens,
                      allow_subannotations,
                      merge_step=False,
                      merge_output_properties_to=None):
    assert not merge_step, 'Merge step is not supported in annotation mode'
    assert not merge_output_properties_to, 'Merge step is not supported in annotation mode'
    # TODO(iannucci): make this use '|' separators instead
    name = '.'.join(name_tokens)
    self.output_root_annotation('SEED_STEP', name)
    return self._create_step_stream(
        name, name_tokens, allow_subannotations, self._outstream)

  def _create_step_stream(
      self, name, name_tokens, allow_subannotations, outstream):
    if allow_subannotations:
      stream = self.AllowSubannotationsStepStream(self, outstream, name)
    else:
      stream = self.StepStream(self, outstream, name)

    if len(name_tokens) > 1:
      # Emit our current nest level, if we are nested.
      stream.output_annotation('STEP_NEST_LEVEL', str(len(name_tokens)-1))
    return stream
