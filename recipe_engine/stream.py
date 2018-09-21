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
import tempfile
import time

from . import env
from . import recipe_api
from . import util


def output_iter(stream, it):
  """Iterates through each string entry in "it", writing it in full to "stream"
  using "write_line".

  This protects against cases where text can't be directly rendered by
  "write_line", notably newlines. In this case, the text will be written via a
  series of "write_line" calls, one for each line.

  A minimum of one "write_line" will be called per item in "it", regardless of
  that item's content.

  Args:
    stream (StreamEngine.Stream): The stream to output to.
    it (iterable): An iterable that yields strings to write.
  """
  for text in it:
    lines = (text.split('\n') if text else ('',))
    for line in lines:
      stream.write_line(line)


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

    def set_build_property(self, key, value):
      raise NotImplementedError()

    def trigger(self, trigger_spec):
      raise NotImplementedError()

    def set_manifest_link(self, name, sha256, url):
      raise NotImplementedError()

  def make_step_stream(self, name, **kwargs):
    """Shorthand for creating a step stream from a step configuration dict."""
    kwargs['name'] = name
    return self.new_step_stream(recipe_api.StepClient.StepConfig(**kwargs))

  def new_step_stream(self, step_config):
    """Creates a new StepStream in this engine.

    The step will be considered started at the moment this method is called.

    TODO(luqui): allow_subannotations is a bit of a hack, whether to allow
    annotations that this step emits through to the annotator (True), or
    guard them by prefixing them with ! (False).  The proper way to do this
    is to implement an annotations parser that converts to StreamEngine calls;
    i.e. parse -> re-emit.

    Args:
      step_config (recipe_api.StepCleint.StepConfig): The step configuration.
    """
    raise NotImplementedError()

  def open(self):
    pass

  def close(self):
    pass

  def __enter__(self):
    self.open()
    return self

  def __exit__(self, _exc_type, _exc_val, _exc_tb):
    self.close()


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

    def close(self):
      self._stream_a.close()
      self._stream_b.close()

  class StepStream(Stream):
    # pylint: disable=no-self-argument
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
    set_build_property = _void_product('set_build_property')
    trigger = _void_product('trigger')
    set_manifest_link = _void_product('set_manifest_link')

  def new_step_stream(self, step_config):
    return self.StepStream(
        self._engine_a.new_step_stream(step_config),
        self._engine_b.new_step_stream(step_config))

  def open(self):
    self._engine_a.open()
    self._engine_b.open()

  def close(self):
    self._engine_a.close()
    self._engine_b.close()


class MultiStreamEngine(StreamEngine):
  """A StreamEngine consisting of one or more inner StreamEngines.

  A call to this StreamEngine will be distributed to the inner StreamEngines.
  Any exceptions that are caught during an inner handler will be deferred until
  all inner handlers have been executed.
  """

  def __init__(self, base, *engines):
    self._engines = (base,) + engines
    assert None not in self._engines

  @classmethod
  def create(cls, *engines):
    assert len(engines) > 0, 'At least one engine must be provided.'
    if len(engines) == 1:
      return engines[0]
    return cls(engines[0], *engines[1:])

  class Stream(StreamEngine.Stream):
    def __init__(self, *streams):
      assert all(streams)
      self._streams = streams

    def write_line(self, line):
      util.map_defer_exceptions(lambda s: s.write_line(line), self._streams)

    def close(self):
      util.map_defer_exceptions(lambda s: s.close(), self._streams)

  class StepStream(Stream):
    # pylint: disable=no-self-argument
    def _multiplex(method_name):
      def inner(self, *args):
        util.map_defer_exceptions(lambda s: getattr(s, method_name)(*args),
                                  self._streams)
      return inner

    def new_log_stream(self, log_name):
      log_streams = []
      try:
        for s in self._streams:
          log_streams.append(s.new_log_stream(log_name))
        return MultiStreamEngine.Stream(*log_streams)
      except Exception:
        # Close any opened log streams.
        util.map_defer_exceptions(lambda ls: ls.close(), log_streams)
        raise

    add_step_text = _multiplex('add_step_text')
    add_step_summary_text = _multiplex('add_step_summary_text')
    add_step_link = _multiplex('add_step_link')
    reset_subannotation_state = _multiplex('reset_subannotation_state')
    set_step_status = _multiplex('set_step_status')
    set_build_property = _multiplex('set_build_property')
    trigger = _multiplex('trigger')

  def new_step_stream(self, step_config):
    return self.StepStream(
        *(se.new_step_stream(step_config)
          for se in self._engines))

  def open(self):
    for se in self._engines:
      se.open()

  def close(self):
    util.map_defer_exceptions(lambda se: se.close(), self._engines)

  def append_stream_engine(self, se):
    assert isinstance(se, StreamEngine)
    self._engines.append(se)


def _noop(*_args, **_kwargs):
  pass

class NoopStreamEngine(StreamEngine):
  class Stream(StreamEngine.Stream):
    write_line = _noop
    close = _noop

  class StepStream(Stream):
    def new_log_stream(self, _log_name):
      return NoopStreamEngine.Stream()
    add_step_text = _noop
    add_step_summary_text = _noop
    add_step_link = _noop
    reset_subannotation_state = _noop
    set_step_status = _noop
    set_build_property = _noop
    trigger = _noop

  def new_step_stream(self, step_config):
    return self.StepStream()


class StreamEngineInvariants(StreamEngine):
  """Checks that the users are using a StreamEngine hygenically.

  Multiply with actually functional StreamEngines so you don't have to check
  these all over the place.
  """
  def __init__(self):
    self._streams = set()

  @classmethod
  def wrap(cls, other):
    """Returns (ProductStreamEngine): A product applying invariants to "other".
    """
    return ProductStreamEngine(cls(), other)

  class StepStream(StreamEngine.StepStream):
    def __init__(self, engine, step_name):
      super(StreamEngineInvariants.StepStream, self).__init__()
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

    def set_build_property(self, key, value):
      pass

    def trigger(self, spec):
      assert '\n' not in spec # Spec must fit on one line.
      json.loads(spec) # Spec must be a valid json object.

    def set_manifest_link(self, name, sha256, url):
      pass

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

  def new_step_stream(self, step_config):
    assert step_config.name not in self._streams, (
        'Step %s already exists' % step_config.name)
    self._streams.add(step_config.name)
    return self.StepStream(self, step_config.name)


class AnnotatorStreamEngine(StreamEngine):
  def __init__(self, outstream, emit_timestamps=False, time_fn=None):
    self._current_step = None
    self._opened = set()
    self._outstream = outstream
    self.emit_timestamps = emit_timestamps
    self.time_fn = time_fn or time.time

  def open(self):
    super(AnnotatorStreamEngine, self).open()
    self.output_current_time()
    self.output_root_annotation('HONOR_ZERO_RETURN_CODE')

  def close(self):
    super(AnnotatorStreamEngine, self).close()
    self.output_current_time()

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
      super(AnnotatorStreamEngine.StepStream, self).__init__()

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

    def new_log_stream(self, log_name):
      return self._engine.StepLogStream(self, log_name)

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

    def set_build_property(self, key, value):
      self.output_annotation('SET_BUILD_PROPERTY', key, value)

    def trigger(self, spec):
      self.output_annotation('STEP_TRIGGER', spec)

    def set_manifest_link(self, name, sha256, url):
      self.output_annotation('SOURCE_MANIFEST', name, sha256.encode('hex'), url)

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


  def new_step_stream(self, step_config):
    self.output_root_annotation('SEED_STEP', step_config.name)
    return self._create_step_stream(step_config, self._outstream)

  def _create_step_stream(self, step_config, outstream):
    if step_config.allow_subannotations:
      stream = self.AllowSubannotationsStepStream(self, outstream,
                                                  step_config.name)
    else:
      stream = self.StepStream(self, outstream, step_config.name)

    if step_config.nest_level > 0:
      # Emit our current nest level, if we are nested.
      stream.output_annotation('STEP_NEST_LEVEL', str(step_config.nest_level))
    return stream

class QuietAnnotatorStreamEngine(AnnotatorStreamEngine):
  def __init__(self, outstream, emit_timestamps=False, time_fn=None,
               tempdir=None):
    super(QuietAnnotatorStreamEngine, self).__init__(
        outstream, emit_timestamps, time_fn)
    self._tempdir = tempdir

  @staticmethod
  def write_annotation(outstream, *args):
    ignored = {
        'STEP_CURSOR',
        'HONOR_ZERO_RETURN_CODE',
    }
    if args[0] in ignored:
      return
    title = {
        'STEP_TEXT': 'Step text:',
        'STEP_STARTED': '-' * 13,
        'SET_BUILD_PROPERTY': 'SET BUILD PROPERTY:',
        'STEP_EXCEPTION': 'STEP EXCEPTION',
        'STEP_FAILURE': 'STEP FAILURE',
        'SEED_STEP': 'STARTED STEP:',
        'STEP_CLOSED': 'FINISHED STEP',
    }.get(args[0])
    if title:
      outstream.flush()
      outstream.write(' '.join((title,) + args[1:]) + '\n')
      outstream.flush()
    else:
      AnnotatorStreamEngine.write_annotation(outstream, *args)

  class StepStream(AnnotatorStreamEngine.StepStream):
    def new_log_stream(self, log_name):
      return self._engine.StepLogStream(self, log_name, self._engine._tempdir)

  class StepLogStream(AnnotatorStreamEngine.StepLogStream):
    def __init__(self, step_stream, log_name, tempdir):
      super(QuietAnnotatorStreamEngine.StepLogStream, self).__init__(
          step_stream, log_name)
      self._step_stream = step_stream
      self._log_name = log_name.replace('/', '&#x2f;')
      self._tempdir = tempdir
      if self._tempdir:
        _, self._quiet_log_location = tempfile.mkstemp(dir=self._tempdir)
        self._quiet_log_f = open(self._quiet_log_location, 'w')

    def write_line(self, line):
      if not self._tempdir:
        super(QuietAnnotatorStreamEngine.StepLogStream, self).write_line(line)
        return

      self._quiet_log_f.write(line+'\n')

    def close(self):
      if not self._tempdir:
        super(QuietAnnotatorStreamEngine.StepLogStream, self).close()
        return

      self._step_stream.write_line('STEP LOG:\'%s\' has been written to %s' % (
          self._log_name, self._quiet_log_location))



def encode_str(s):
  """Tries to encode a string into a python str type.

  Currently buildbot only supports ascii. If we have an error decoding the
  string (which means it might not be valid ascii), we decode the string with
  the 'replace' error mode, which replaces invalid characters with a suitable
  replacement character.
  """
  try:
    return str(s)
  except UnicodeEncodeError:
    return s.encode('utf-8', 'replace')
  except UnicodeDecodeError:
    return s.decode('utf-8', 'replace')
