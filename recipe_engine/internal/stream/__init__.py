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


class StreamEngine(object):
  class Stream(object):
    def write_line(self, line):
      raise NotImplementedError()

    def write_split(self, string):
      """Write a string (which may contain newlines) to the stream.  It will
      be terminated by a newline."""
      for actual_line in string.splitlines() or ['']: # preserve empty lines
        self.write_line(actual_line)

    # TODO(iannucci): Having a phantom method as part of the API is weird.
    # If there's a real filelike for this Stream, return it.
    #
    # Otherwise don't implement this.
    # def fileno(self):

    def close(self):
      raise NotImplementedError()

    # TODO(iannucci): make handle_exception unnecessary
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

    def set_step_status(self, status, had_timeout):
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


  def new_step_stream(self, name_tokens, allow_subannotations):
    """Creates a new StepStream in this engine.

    The step will be considered started at the moment this method is called.

    TODO(luqui): allow_subannotations is a bit of a hack, whether to allow
    annotations that this step emits through to the annotator (True), or
    guard them by prefixing them with ! (False).  The proper way to do this
    is to implement an annotations parser that converts to StreamEngine calls;
    i.e. parse -> re-emit.

    Args:
      * name_tokens (Tuple[basestring]): The name of the step to run, including
        all namespaces.
      * allow_subannotations (bool): If True, tells the StreamEngine to expect
        the old @@@annotator@@@ protocol to be emitted on stdout from this
        step.
    """
    raise NotImplementedError()

  def open(self):
    pass

  def close(self):
    pass

  # TODO(iannucci): make handle_exception unnecessary
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
