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


class StreamEngine:
  class Stream:
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

    def append_log(self, log):
      """Appends an existing log stream (common_pb2.Log proto msg) directly to
      step logs.
      """
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

    def set_summary_markdown(self, text):
      """Only on luciexe."""
      raise NotImplementedError()

    def set_step_tag(self, key, value):
      pass

    def mark_running(self):
      pass

    def open_std_handles(self, stdout=False, stderr=False):
      """Opens one or two standard handles.

      Returns:
        None - This StepStream cannot handle the request (e.g. Invariants).
        {handlename: handle} - The mapping of file descriptors for the requested
           handles. Note that multiple handles may be the same value (if the two
           streams are both sunk to the same output). If `handle` is `self`,
           then writes will be handled by StepStream.write_line.
      """
      return None

    @property
    def env_vars(self):
      """Returns a dict of environment variable overrides for this step."""
      return {}

    @property
    def user_namespace(self):
      """Only on luciexe and needed when the step is a merge step"""
      return None

  def new_step_stream(self,
                      name_tokens,
                      allow_subannotations,
                      merge_step=False,
                      merge_output_properties_to: None | list[str] = None):
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
      * merge_step (True,False,"legacy"): If True, tells the StreamEngine to
        create a step stream that denotes a merge step. This is only valid for
        luciexe protocol. If set to "legacy" then this merge step will also
        set the legacy_global_namespace option.
    """
    raise NotImplementedError()

  def open(self):
    pass

  def close(self):
    pass

  @property
  def supports_concurrency(self):
    """Return True iff this StreamEngine implementation supports concurrent
    step execution."""
    raise NotImplementedError()

  def write_result(self, result):
    """Write recipe execution result (type: result_pb2.RawResult).

    Note: Only implemented in luciexe.
    """
    raise NotImplementedError()

  def __enter__(self):
    self.open()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.close()
    return True


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
