# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

from ...types import StepPresentation

from . import StreamEngine
from .product import ProductStreamEngine


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

  @property
  def supports_concurrency(self):
    return True

  def write_result(self, result):
    assert isinstance(result, result_pb2.RawResult), (
      'expected type result_pb2.RawResult; got %s' % (type(result), ))
    assert result.status & common_pb2.ENDED_MASK, (
      'expected terminal build status; got %s' % result.status)

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
        if isinstance(log, self._engine.LogStream):
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

    def append_log(self, log):
      assert self._open
      assert isinstance(log, common_pb2.Log), (
        'expected type common_pb2.Log; got type %s' % (type(log),))
      assert log.name not in self._logs, 'Log %s already exists in step %s' % (
        log.name, self._step_name)
      self._logs[log.name] = None # The instance is not needed

    def add_step_text(self, text):
      pass

    def add_step_summary_text(self, text):
      pass

    def set_summary_markdown(self, text):
      pass

    def add_step_link(self, name, url):
      assert isinstance(name, basestring), 'Link name %s is not a string' % name
      assert isinstance(url, basestring), 'Link url %s is not a string' % url

    def set_step_status(self, status, had_timeout):
      _ = had_timeout
      assert status in StepPresentation.STATUSES, 'Unknown status %r' % status
      if status == 'SUCCESS':
        # A constraint imposed by the annotations implementation
        assert self._status == 'SUCCESS', (
          'Cannot set successful status after status is %s' % self._status)
      self._status = status

    def set_build_property(self, key, value):
      pass

  class LogStream(StreamEngine.Stream):
    def __init__(self, step_stream, log_name):
      self._step_stream = step_stream
      self._log_name = log_name
      self._open = True

    def write_line(self, line):
      assert '\n' not in line, 'Newline in %r' % (line,)
      assert self._step_stream._open
      assert self._open

    def close(self):
      assert self._step_stream._open
      assert self._open
      self._open = False

  def new_step_stream(self, name_tokens, allow_subannotations,
                      merge_step=False):
    del allow_subannotations, merge_step

    if any('|' in token for token in name_tokens):
      raise ValueError(
          'The pipe ("|") character is reserved in step names: %r'
          % (name_tokens,))

    name = '|'.join(name_tokens)
    assert name not in self._streams, 'Step %r already exists' % (name,)
    self._streams.add(name)
    return self.StepStream(self, name)
