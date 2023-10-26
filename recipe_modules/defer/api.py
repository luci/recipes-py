# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Runs a function but defers the result until a later time."""

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

    # TODO: crbug.com/1495428 - Simplify format_exception call once switched to
    # Python 3.10+.
    return traceback.format_exception(
        etype=type(self._exc), value=self._exc, tb=self._exc.__traceback__)

  def is_ok(self) -> bool:
    return not self._exc

  def result(self) -> T:
    """Raise the exception or return the original return value."""
    if self._exc:
      step = self._api.step.empty('result', status='FAILURE',
                                  raise_on_failure=False)
      step.presentation.logs['traceback'] = self._traceback()
      self._api.step.close_non_nest_step()
      raise self._exc
    return self._value


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
      step_name: str = 'collect',
  ) -> Sequence[Any]:
    """Raise any exceptions in the given list of DeferredResults.

    If there are no exceptions, do nothing. If there are one or more exceptions,
    reraise one of the worst of them.
    """
    if all(x.is_ok() for x in results):
      return [x.result() for x in results]

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
