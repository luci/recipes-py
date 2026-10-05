# Copyright 2015 The LUCI Authors
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

from __future__ import annotations

from collections.abc import Sequence
import types
from typing import Any, Literal, Self

from PB.recipe_engine import result as result_pb


class StreamEngine:
  class Stream:
    def write_line(self, line: str) -> None:
      raise NotImplementedError()

    def write_split(self, string: str) -> None:
      """Write a string (which may contain newlines) to the stream.  It will
      be terminated by a newline."""
      for actual_line in string.splitlines() or ['']: # preserve empty lines
        self.write_line(actual_line)

    # TODO(iannucci): Having a phantom method as part of the API is weird.
    # If there's a real filelike for this Stream, return it.
    #
    # Otherwise don't implement this.
    # def fileno(self):

    def close(self) -> None:
      raise NotImplementedError()

    # TODO(iannucci): make handle_exception unnecessary
    def handle_exception(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool | None:
      pass

    def __enter__(self) -> Self:
      return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool | None:
      ret = self.handle_exception(exc_type, exc_val, exc_tb)
      self.close()
      return ret

  class StepStream(Stream):
    def new_log_stream(self, log_name: str) -> StreamEngine.Stream:
      raise NotImplementedError()

    def append_log(self, log: Any) -> None:
      """Appends an existing log stream (common_pb2.Log proto msg) directly to
      step logs.
      """
      raise NotImplementedError()

    def add_step_text(self, text: str) -> None:
      raise NotImplementedError()

    def add_step_summary_text(self, text: str) -> None:
      raise NotImplementedError()

    def add_step_link(self, name: str, url: str) -> None:
      raise NotImplementedError()

    def reset_subannotation_state(self) -> None:
      pass

    def set_step_status(self, status: str, had_timeout: bool) -> None:
      raise NotImplementedError()

    def set_build_property(self, key: str, value: str) -> None:
      raise NotImplementedError()

    def set_summary_markdown(self, text: str) -> None:
      """Only on luciexe."""
      raise NotImplementedError()

    def set_step_tag(self, key: str, value: str) -> None:
      pass

    def mark_running(self) -> None:
      pass

    def open_std_handles(
        self, stdout: bool = False, stderr: bool = False
    ) -> dict[str, StreamEngine.Stream] | None:
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
    def env_vars(self) -> dict[str, str]:
      """Returns a dict of environment variable overrides for this step."""
      return {}

    @property
    def user_namespace(self) -> str | None:
      """Only on luciexe and needed when the step is a merge step"""
      return None

  def new_step_stream(
      self,
      name_tokens: Sequence[str],
      allow_subannotations: bool,
      merge_step: bool | Literal['legacy'] = False,
      merge_output_properties_to: Sequence[str] | None = None,
  ) -> StepStream:
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

  def open(self) -> None:
    pass

  def close(self) -> None:
    pass

  @property
  def supports_concurrency(self) -> bool:
    """Return True iff this StreamEngine implementation supports concurrent
    step execution."""
    raise NotImplementedError()

  def write_result(self, result: result_pb.RawResult) -> None:
    """Write recipe execution result (type: result_pb2.RawResult).

    Note: Only implemented in luciexe.
    """
    raise NotImplementedError()

  def __enter__(self) -> Self:
    self.open()
    return self

  def __exit__(
      self,
      exc_type: type[BaseException] | None,
      exc_val: BaseException | None,
      exc_tb: types.TracebackType | None,
  ) -> bool:
    self.close()
    return True


def encode_str(s: Any) -> str:
  """Tries to encode a string into a python str type.

  Currently buildbot only supports ascii. If we have an error decoding the
  string (which means it might not be valid ascii), we decode the string with
  the 'replace' error mode, which replaces invalid characters with a suitable
  replacement character.
  """
  try:
    return str(s)
  except UnicodeEncodeError:
    return s.encode('utf-8', 'replace').decode('utf-8', 'replace')
  except UnicodeDecodeError:
    return s.decode('utf-8', 'replace')
