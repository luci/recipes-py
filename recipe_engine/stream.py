# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Abstract stream interface for representing recipe runs.

We need to create streams for steps (and substeps) and also LOG_LINE steps.
LogDog will implement LOG_LINE steps as real logs (i.e. uniformly), but
annotations will implement them differently from normal logs, so we need
a way to distinguish.

StreamEngine will coordinate the multiplexing of streams.  In the case of
annotations, this involves keeping track of the STEP_CURSOR and setting it
accordingly, as well as filtering @@@ lines.

Stream is a virtual well-behaved stream (associated with an Engine) which you
can just write to without worrying.
"""

import json

class StreamEngine(object):
  class Stream(object):
    def write_line(self, line):
      raise NotImplementedError()

    def write_split(self, string):
      """Write a string (which may contain newlines) to the stream.  It will
      be terminated by a newline."""
      for actual_line in string.splitlines() or ['']: # preserve empty lines
        self.write_line(actual_line)

    def close(self):
      raise NotImplementedError()

    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc_val, exc_tb):
      self.close()

  class StepStream(Stream):
    def new_log_stream(self, log_name):
      raise NotImplementedError()

    def add_step_text(self, text):
      raise NotImplementedError()

    def add_step_summary_text(self, text):
      raise NotImplementedError()

    def add_step_link(self, name, url):
      raise NotImplementedError()

    def reset_subannotation_state(self):
      pass

    def set_step_status(self, status):
      raise NotImplementedError()

    def set_nest_level(self, nest_level):
      raise NotImplementedError()

    def set_build_property(self, key, value):
      raise NotImplementedError()

    def trigger(self, trigger_spec):
      raise NotImplementedError()

  def new_step_stream(self, step_name, allow_subannotations=False):
    """Craete a new StepStream in this engine.

    The step will be considered started at the moment this method is called.

    TODO(luqui): allow_subannotations is a bit of a hack, whether to allow
    annotations that this step emits through to the annotator (True), or
    guard them by prefixing them with ! (False).  The proper way to do this
    is to implement an annotations parser that converts to StreamEngine calls;
    i.e. parse -> re-emit.
    """

    raise NotImplementedError()


# Because StreamEngine has no observations (i.e. it is an F-Algebra), we can
# form products.  This code is entirely mechanical from the types (if we
# had them formalized...).
class ProductStreamEngine(StreamEngine):
  def __init__(self, engine_a, engine_b):
    self._engine_a = engine_a
    self._engine_b = engine_b

  class Stream(StreamEngine.Stream):
    def __init__(self, stream_a, stream_b):
      self._stream_a = stream_a
      self._stream_b = stream_b

    def write_line(self, line):
      self._stream_a.write_line(line)
      self._stream_b.write_line(line)

    def close(self):
      self._stream_a.close()
      self._stream_b.close()

  class StepStream(Stream):
    def _void_product(method_name):
      def inner(self, *args):
        getattr(self._stream_a, method_name)(*args)
        getattr(self._stream_b, method_name)(*args)
      return inner

    def new_log_stream(self, log_name):
      return ProductStreamEngine.Stream(
          self._stream_a.new_log_stream(log_name),
          self._stream_b.new_log_stream(log_name))

    add_step_text = _void_product('add_step_text')
    add_step_summary_text = _void_product('add_step_summary_text')
    add_step_link = _void_product('add_step_link')
    reset_subannotation_state = _void_product('reset_subannotation_state')
    set_step_status = _void_product('set_step_status')
    set_nest_level = _void_product('set_nest_level')
    set_build_property = _void_product('set_build_property')
    trigger = _void_product('trigger')

  def new_step_stream(self, step_name, allow_subannotations=False):
    return self.StepStream(
        self._engine_a.new_step_stream(step_name, allow_subannotations),
        self._engine_b.new_step_stream(step_name, allow_subannotations))


def _noop(*args, **kwargs):
  pass

class NoopStreamEngine(StreamEngine):
  class Stream(StreamEngine.Stream):
    write_line = _noop
    close = _noop

  class StepStream(Stream):
    def new_log_stream(self, log_name):
      return NoopStreamEngine.Stream()
    add_step_text = _noop
    add_step_summary_text = _noop
    add_step_link = _noop
    reset_subannotation_state = _noop
    set_step_status = _noop
    set_nest_level = _noop
    set_build_property = _noop
    trigger = _noop

  def new_step_stream(self, step_name, allow_subannotations=False):
    return self.StepStream()


class StreamEngineInvariants(StreamEngine):
  """Checks that the users are using a StreamEngine hygenically.

  Multiply with actually functional StreamEngines so you don't have to check
  these all over the place.
  """
  def __init__(self):
    self._streams = set()

  class StepStream(StreamEngine.StepStream):
    def __init__(self, engine, step_name):
      self._engine = engine
      self._step_name = step_name
      self._open = True
      self._logs = {}
      self._status = 'SUCCESS'

    def write_line(self, line):
      assert '\n' not in line
      assert self._open

    def close(self):
      assert self._open
      for log_name, log in self._logs.iteritems():
        assert not log._open, 'Log %s still open when closing step %s' % (
          log_name, self._step_name)
      self._open = False

    def new_log_stream(self, log_name):
      assert self._open
      assert log_name not in self._logs, 'Log %s already exists in step %s' % (
          log_name, self._step_name)
      ret = self._engine.LogStream(self, log_name)
      self._logs[log_name] = ret
      return ret

    def add_step_text(self, text):
      pass

    def add_step_summary_text(self, text):
      pass

    def add_step_link(self, name, url):
      assert isinstance(name, basestring), 'Link name %s is not a string' % name
      assert isinstance(url, basestring), 'Link url %s is not a string' % url

    def set_step_status(self, status):
      assert status in ('SUCCESS', 'WARNING', 'FAILURE', 'EXCEPTION')
      if status == 'SUCCESS':
        # A constraint imposed by the annotations implementation
        assert self._status == 'SUCCESS', (
          'Cannot set successful status after status is %s' % self._status)
      self._status = status

    def set_nest_level(self, nest_level):
      assert isinstance(nest_level, int)

    def set_build_property(self, key, value):
      pass

    def trigger(self, spec):
      assert '\n' not in spec # Spec must fit on one line.
      json.loads(spec) # Spec must be a valid json object.

  class LogStream(StreamEngine.Stream):
    def __init__(self, step_stream, log_name):
      self._step_stream = step_stream
      self._log_name = log_name
      self._open = True

    def write_line(self, line):
      assert '\n' not in line
      assert self._step_stream._open
      assert self._open

    def close(self):
      assert self._step_stream._open
      assert self._open
      self._open = False

  def new_step_stream(self, step_name, allow_subannotations=False):
    assert step_name not in self._streams, 'Step %s already exists' % step_name
    self._streams.add(step_name)
    return self.StepStream(self, step_name)


class AnnotationStepStream(StreamEngine.StepStream):
  def basic_write(self, line):
    raise NotImplementedError()

  def output_annotation(self, *args):
    self.basic_write('@@@' + '@'.join(args) + '@@@\n')

  def write_line(self, line):
    if line.startswith('@@@'):
      self.basic_write('!' + line + '\n')
    else:
      self.basic_write(line + '\n')

  def close(self):
    self.output_annotation('STEP_CLOSED')

  def new_log_stream(self, log_name):
    return self.StepLogStream(self, log_name)

  def add_step_text(self, text):
    self.output_annotation('STEP_TEXT', text)

  def add_step_summary_text(self, text):
    self.output_annotation('STEP_SUMMARY_TEXT', text)

  def add_step_link(self, name, url):
    self.output_annotation('STEP_LINK', name, url)

  def set_step_status(self, status):
    if status == 'SUCCESS':
      pass
    elif status == 'WARNING':
      self.output_annotation('STEP_WARNINGS')
    elif status == 'FAILURE':
      self.output_annotation('STEP_FAILURE')
    elif status == 'EXCEPTION':
      self.output_annotation('STEP_EXCEPTION')
    else:
      raise Exception('Impossible status %s' % status)

  def set_nest_level(self, nest_level):
    self.output_annotation('STEP_NEST_LEVEL', str(nest_level))

  def set_build_property(self, key, value):
    self.output_annotation('SET_BUILD_PROPERTY', key, value)

  def trigger(self, spec):
    self.output_annotation('STEP_TRIGGER', spec)

  class StepLogStream(StreamEngine.Stream):
    def __init__(self, step_stream, log_name):
      self._step_stream = step_stream
      self._log_name = log_name.replace('/', '&#x2f;')

    def write_line(self, line):
      self._step_stream.output_annotation('STEP_LOG_LINE', self._log_name, line)

    def close(self):
      self._step_stream.output_annotation('STEP_LOG_END', self._log_name)


class AnnotatorStreamEngine(StreamEngine):
  def __init__(self, outstream):
    self._current_step = None
    self._opened = set()
    self._outstream = outstream
    self.output_annotation('HONOR_ZERO_RETURN_CODE')

  def output_annotation(self, *args):
    # Flush the stream before & after engine annotations, because they can
    # change which step we are talking about and this matters to buildbot.
    self._outstream.flush()
    self._outstream.write('@@@' + '@'.join(args) + '@@@\n')
    self._outstream.flush()

  def _step_cursor(self, name):
    if self._current_step != name:
      self.output_annotation('STEP_CURSOR', name)
      self._current_step = name
    if name not in self._opened:
      self.output_annotation('STEP_STARTED')
      self._opened.add(name)

  class StepStream(AnnotationStepStream):
    def __init__(self, engine, step_name):
      self._engine = engine
      self._step_name = step_name

    def basic_write(self, line):
      self._engine._step_cursor(self._step_name)
      self._engine._outstream.write(line)

  class AllowSubannotationsStepStream(StepStream):
    def write_line(self, line):
      self.basic_write(line + '\n')

    # HACK(luqui): If the subannotator script changes the active step, we need
    # a way to get back to the real step that spawned the script.  The right
    # way to do that is to parse the annotation stream and re-emit it.  But for
    # now we just provide this method.
    def reset_subannotation_state(self):
      self._engine._current_step = None

  def new_step_stream(self, step_name, allow_subannotations=False):
    self.output_annotation('SEED_STEP', step_name)
    if allow_subannotations:
      return self.AllowSubannotationsStepStream(self, step_name)
    else:
      return self.StepStream(self, step_name)


class BareAnnotationStepStream(AnnotationStepStream):
  """A StepStream that is not tied to any engine, and emits assuming it has the
  cursor.

  This is used for capturing the annotations in the engine.
  """
  def __init__(self, outstream):
    self._outstream = outstream

  def basic_write(self, line):
    self._outstream.write(line)

