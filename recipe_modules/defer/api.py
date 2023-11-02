# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Runs a function but defers the result until a later time."""

import contextlib
import dataclasses
import functools
import traceback
from typing import Any, Callable, Generic, Optional, Sequence, TypeVar

from recipe_engine import recipe_api


T = TypeVar('T')


@dataclasses.dataclass(frozen=True)
class DeferredResult(Generic[T]):
  _api: recipe_api.RecipeApi
  _value: Optional[T] = None
  _exc: Optional[Exception] = None

  def _traceback(self) -> Optional[str]:
    if self.is_ok():
      return None  # pragma: no cover
    return '\n'.join(traceback.format_exception(self._exc))

  def is_ok(self) -> bool:
    return not self._exc

  def result(self, step_name: Optional[str] = None) -> T:
    """Raise the exception or return the original return value.

    Args:
        step_name: Name for step including the traceback log if there was a
            failure. If None, don't include a step with traceback logs.
    """
    if self._exc:
      if step_name:
        step = self._api.step.empty(step_name, status='FAILURE',
                                    raise_on_failure=False)
        step.presentation.logs['traceback'] = self._traceback()
        self._api.step.close_non_nest_step()
      raise self._exc
    # We ignore the type here because we actually know it's T (which COULD BE
    # None, so we can't really test for that).
    return self._value  # type:ignore


class _DeferContext:
  def __init__(self, api, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.api = api
    self.results = []

  def __call__(
      self, callable: Callable[..., T], *args, **kwargs
  ) -> DeferredResult[T]:
    result = self.api.defer(callable, *args, **kwargs)
    self.results.append(result)
    return result

  def collect(self, step_name: Optional[str] = 'collect'):
    self.api.defer.collect(self.results, step_name=step_name)


class DeferApi(recipe_api.RecipeApi):
  """Runs a function but defers the result until a later time.

  Exceptions caught by api.defer() will show in MILO as they occur, but won't
  continue to propagate the exception until api.defer.collect() or
  DeferredResult.result() is called.

  For StepFailures and InfraFailures, MILO already includes the failure output.
  For other exceptions, api.defer() will add a step showing the exception and
  continue.

  Details about individual failures cannot yet be reliably retrieved when
  calling api.defer.collect(), but .result() can be called on individual
  DeferredResults to re-raise individual failures.

  If there are no failures, api.defer.collect() returns a Sequence of the
  return values of the functions passed into api.defer().
  """

  DeferredResult = DeferredResult

  @contextlib.contextmanager
  def context(self, collect_step_name: Optional[str] = 'collect'):
    """Creates a context that tracks deferred calls.

    Usage:

    with api.defer.context() as defer:
      defer(api.step, ...)
      defer(api.step, ...)
      ...
    # api.defer.collect() is called on exiting the context.
    """
    ctx = _DeferContext(self.m)

    # try:
    yield ctx
    # TODO: crbug.com/1495428 - Use an ExceptionGroup to combine any
    # non-deferred exceptions from within the try with deferred exceptions.
    ctx.collect(step_name=collect_step_name)

  def __call__(
      self, func: Callable[..., T], *args, **kwargs
  ) -> DeferredResult[T]:
    """Calls func(*args, **kwargs) but catches all exceptions.

    Returns a DeferredResult. If the call returns a value, the DeferredResult
    contains that value. If the call raises an exception, the DeferredResult
    contains that exception.

    The DeferredResult is expected to be passed into api.defer.collect(), but
    DeferredResult.result() does similar processing.
    """
    try:
      return DeferredResult(_api=self.m, _value=func(*args, **kwargs))
    except Exception as exc:
      return DeferredResult(_api=self.m, _exc=exc)

  def _raise(self, results: Sequence[DeferredResult]) -> None:
    """Re-raise the "worst" failure in results.

    StepFailures are "best", followed by InfraFailures, followed by all other
    exceptions.

    TODO: crbug.com/1495428 - Use ExceptionGroups once we support Python 3.11.
    """
    failing_results = [x for x in results if not x.is_ok()]

    for result in failing_results:
      if not isinstance(result._exc, self.m.step.StepFailure):
        raise result._exc

    for result in failing_results:
      if isinstance(result._exc, self.m.step.InfraFailure):
        raise result._exc

    for result in failing_results:
      if result._exc:
        raise result._exc

    raise ValueError(  # pragma: no cover
        '_raise() called but no results contained exceptions')

  def collect(
      self,
      results: Sequence[DeferredResult],
      step_name: Optional[str] = 'collect',
  ) -> Sequence[Any]:
    """Raise any exceptions in the given list of DeferredResults.

    If there are no exceptions, do nothing. If there are one or more exceptions,
    reraise one of the worst of them.

    Args:
        results: Results to check.
        step_name: Name for step including traceback logs if there are failures.
            If None, don't include a step with traceback logs.
    """
    if all(x.is_ok() for x in results):
      return [x.result() for x in results]

    if step_name:
      failures = [x for x in results if not x.is_ok()]

      traces_by_name = {}
      for result in failures:
        name = repr(result._exc)
        traces_by_name.setdefault(name, [])
        traces_by_name[name].append(result._traceback())

      step = self.m.step.empty(step_name, status='FAILURE',
                               step_text=f'{len(failures)} deferred failures',
                               raise_on_failure=False)
      for name, traces in traces_by_name.items():
        for i, trace in enumerate(traces):
          number_part = f' ({i+1})' if i else ''
          step.presentation.logs[f'{name}{number_part}'] = trace

    raise self._raise(results)
