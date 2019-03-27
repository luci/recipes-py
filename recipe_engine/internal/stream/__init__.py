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
import logging
import tempfile
import time

from ..engine_step import StepConfig


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

    def fileno(self):
      """If this has a real file descriptor, return it (int).

      Otherwise return self."""
      return self

    def close(self):
      raise NotImplementedError()

    def handle_exception(self, exc_type, exc_val, exc_tb):
      pass

    def __enter__(self):
      return self

    def __exit__(self, exc_type, exc_val, exc_tb):
      ret = self.handle_exception(exc_type, exc_val, exc_tb)
      self.close()
      return ret

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

    # The StepStreams that this step should use for stdout/stderr.
    #
    # @property
    # def stdout(self): return StepStream
    #
    # @property
    # def stderr(self): return StepStream
    #
    # These are omitted from the base implementation so that ProductStreamEngine
    # will pick and return the value from real StreamEngine, not
    # StreamEngineInvariants.


  def make_step_stream(self, name):
    """Shorthand for creating a root-level step stream."""
    # TODO(iannucci): remove this method
    return self.new_step_stream(StepConfig(name_tokens=(name,)))

  def new_step_stream(self, step_config):
    """Creates a new StepStream in this engine.

    The step will be considered started at the moment this method is called.

    TODO(luqui): allow_subannotations is a bit of a hack, whether to allow
    annotations that this step emits through to the annotator (True), or
    guard them by prefixing them with ! (False).  The proper way to do this
    is to implement an annotations parser that converts to StreamEngine calls;
    i.e. parse -> re-emit.

    Args:
      step_config (StepConfig): The step configuration.
    """
    raise NotImplementedError()

  def open(self):
    pass

  def close(self):
    pass

  def handle_exception(self, exc_type, exc_val, exc_tb):
    pass

  def __enter__(self):
    self.open()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    ret = self.handle_exception(exc_type, exc_val, exc_tb)
    self.close()
    return ret


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
