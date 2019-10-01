# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from . import StreamEngine


class ProductStreamEngine(StreamEngine):
  """A StreamEngine that forms the non-commutative product of two other
  StreamEngines.

  Because StreamEngine has no observations (i.e. it is an F-Algebra), we can
  form products.  This code is entirely mechanical from the types (if we
  had them formalized...).

  This product is non-commutative, meaning order matters. Specifically, an
  exception in "engine_a" will prevent "engine_b" from being evaluated.
  """

  def __init__(self, engine_a, engine_b):
    assert engine_a and engine_b
    self._engine_a = engine_a
    self._engine_b = engine_b

  class Stream(StreamEngine.Stream):
    def __init__(self, stream_a, stream_b):
      assert stream_a and stream_b
      self._stream_a = stream_a
      self._stream_b = stream_b

    def write_line(self, line):
      self._stream_a.write_line(line)
      self._stream_b.write_line(line)

    def handle_exception(self, exc_type, exc_val, exc_tb):
      ret = self._stream_a.handle_exception(exc_type, exc_val, exc_tb)
      ret = ret or self._stream_b.handle_exception(exc_type, exc_val, exc_tb)
      return ret

    def __getattr__(self, name):
      if name == 'fileno':
        if hasattr(self._stream_a, 'fileno'):
          return self._stream_a.fileno
        if hasattr(self._stream_b, 'fileno'):
          return self._stream_b.fileno
      return object.__getattribute__(self, name)

    def close(self):
      self._stream_a.close()
      self._stream_b.close()

  class StepStream(Stream):
    # pylint: disable=no-self-argument
    def _void_product(method_name):
      def inner(self, *args, **kwargs):
        getattr(self._stream_a, method_name)(*args, **kwargs)
        getattr(self._stream_b, method_name)(*args, **kwargs)
      return inner

    def new_log_stream(self, log_name):
      return ProductStreamEngine.Stream(
          self._stream_a.new_log_stream(log_name),
          self._stream_b.new_log_stream(log_name))

    @property
    def stdout(self):
      return getattr(
          self._stream_a, 'stdout', getattr(
              self._stream_b, 'stdout', self))

    @property
    def stderr(self):
      return getattr(
          self._stream_a, 'stderr', getattr(
              self._stream_b, 'stderr', self))

    def handle_exception(self, exc_type, exc_val, exc_tb):
      ret = self._stream_a.handle_exception(exc_type, exc_val, exc_tb)
      ret = ret or self._stream_b.handle_exception(exc_type, exc_val, exc_tb)
      return ret

    add_step_text = _void_product('add_step_text')
    add_step_summary_text = _void_product('add_step_summary_text')
    add_step_link = _void_product('add_step_link')
    reset_subannotation_state = _void_product('reset_subannotation_state')
    set_step_status = _void_product('set_step_status')
    set_build_property = _void_product('set_build_property')
    trigger = _void_product('trigger')
    set_manifest_link = _void_product('set_manifest_link')
    mark_running = _void_product('mark_running')

  def new_step_stream(self, name_tokens, allow_subannotations):
    return self.StepStream(
        self._engine_a.new_step_stream(name_tokens, allow_subannotations),
        self._engine_b.new_step_stream(name_tokens, allow_subannotations))

  def open(self):
    self._engine_a.open()
    self._engine_b.open()

  def handle_exception(self, exc_type, exc_val, exc_tb):
    ret = self._engine_a.handle_exception(exc_type, exc_val, exc_tb)
    ret = ret or self._engine_b.handle_exception(exc_type, exc_val, exc_tb)
    return ret

  def close(self):
    self._engine_a.close()
    self._engine_b.close()

  @property
  def supports_concurrency(self):
    return (
      self._engine_a.supports_concurrency and
      self._engine_b.supports_concurrency)
