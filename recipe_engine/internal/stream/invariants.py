# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb
from PB.recipe_engine import result as result_pb

from ... import engine_types

from .. import stream as stream_mod
from . import product


class StreamEngineInvariants(stream_mod.StreamEngine):
  """Checks that the users are using a StreamEngine hygenically.

  Multiply with actually functional StreamEngines so you don't have to check
  these all over the place.
  """
  def __init__(self) -> None:
    self._streams: set[str] = set()

  @classmethod
  def wrap(
      cls, other: stream_mod.StreamEngine
  ) -> product.ProductStreamEngine:
    """Returns (ProductStreamEngine): A product applying invariants to "other".
    """
    return product.ProductStreamEngine(cls(), other)

  @property
  def supports_concurrency(self) -> bool:
    return True

  def write_result(self, result: result_pb.RawResult) -> None:
    assert isinstance(result, result_pb.RawResult), (
      'expected type result_pb2.RawResult; got %s' % (type(result), ))
    assert result.status & common_pb.ENDED_MASK, (
      'expected terminal build status; got %s' % result.status)

  class StepStream(stream_mod.StreamEngine.StepStream):
    def __init__(
        self, engine: StreamEngineInvariants, step_name: str
    ) -> None:
      super().__init__()
      self._engine = engine
      self._step_name = step_name
      self._open = True
      self._logs: dict[str, StreamEngineInvariants.LogStream | None] = {}
      self._status = 'SUCCESS'

    def write_line(self, line: str) -> None:
      assert '\n' not in line
      assert self._open

    def close(self) -> None:
      assert self._open
      for log_name, log in self._logs.items():
        if isinstance(log, self._engine.LogStream):
          assert not log._open, 'Log %s still open when closing step %s' % (
            log_name, self._step_name)
      self._open = False

    def new_log_stream(
        self, log_name: str
    ) -> StreamEngineInvariants.LogStream:
      assert self._open
      assert log_name not in self._logs, 'Log %s already exists in step %s' % (
        log_name, self._step_name)
      ret = self._engine.LogStream(self, log_name)
      self._logs[log_name] = ret
      return ret

    def append_log(self, log: common_pb.Log) -> None:
      assert self._open
      assert isinstance(log, common_pb.Log), (
        'expected type common_pb2.Log; got type %s' % (type(log),))
      assert log.name not in self._logs, 'Log %s already exists in step %s' % (
        log.name, self._step_name)
      self._logs[log.name] = None # The instance is not needed

    def add_step_text(self, text: str) -> None:
      pass

    def add_step_summary_text(self, text: str) -> None:
      pass

    def set_summary_markdown(self, text: str) -> None:
      pass

    def add_step_link(self, name: str, url: str) -> None:
      assert isinstance(name, str), 'Link name %s is not a string' % name
      assert isinstance(url, str), 'Link url %s is not a string' % url

    def set_step_status(self, status: str, had_timeout: bool) -> None:
      _ = had_timeout
      assert status in engine_types.StepPresentation.STATUSES, (
          'Unknown status %r' % status)
      if status == 'SUCCESS':
        # A constraint imposed by the annotations implementation
        assert self._status == 'SUCCESS', (
          'Cannot set successful status after status is %s' % self._status)
      self._status = status

    def set_build_property(self, key: str, value: str) -> None:
      pass

    def set_step_tag(self, key: str, value: str) -> None:
      assert isinstance(key, str), 'Step Tag key %s is not a string' % key
      assert isinstance(value, str), 'Step Tag value %s is not a string' % value
      assert key != '', 'Step Tag key %s is empty' % key
      assert value != '', 'Step Tag value %s is empty' % value

  class LogStream(stream_mod.StreamEngine.Stream):
    def __init__(
        self,
        step_stream: StreamEngineInvariants.StepStream,
        log_name: str,
    ) -> None:
      self._step_stream = step_stream
      self._log_name = log_name
      self._open = True

    def write_line(self, line: str) -> None:
      assert '\n' not in line, 'Newline in %r' % (line,)
      assert self._step_stream._open
      assert self._open

    def close(self) -> None:
      assert self._step_stream._open
      assert self._open
      self._open = False

  def new_step_stream(
      self,
      name_tokens: Sequence[str],
      allow_subannotations: bool,
      merge_step: bool | Literal['legacy'] = False,
      merge_output_properties_to: Sequence[str] | None = None,
  ) -> StepStream:
    del allow_subannotations, merge_step, merge_output_properties_to

    if any('|' in token for token in name_tokens):
      raise ValueError(
          'The pipe ("|") character is reserved in step names: %r'
          % (name_tokens,))

    name = '|'.join(name_tokens)
    assert name not in self._streams, 'Step %r already exists' % (name,)
    self._streams.add(name)
    return self.StepStream(self, name)
