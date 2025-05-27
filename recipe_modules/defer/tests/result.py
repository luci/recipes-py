# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from typing import Generator

from PB.recipe_modules.recipe_engine.defer.tests import (
    properties as properties_pb2
)
from recipe_engine import post_process, recipe_test_api, step_data

DEPS = [
    'context',
    'defer',
    'properties',
    'step',
]

PROPERTIES = properties_pb2.ResultInputProps


class ResultTestError(Exception):
    pass


def RunSteps(api, props):
  def _fake_step():
    with api.context(infra_steps=props.infra_steps):
      api.step('step', ['cmd'])
      if props.exception:
        raise ResultTestError()
      return 5

  deferred = api.defer(_fake_step)
  if deferred.is_ok():
    api.step('is ok', None)
  deferred.result(step_name=props.step_name or None)
  api.step('step succeeded', None)
  with api.step.nest('result') as pres:
    pres.step_summary_text = repr(deferred.result())


def GenTests(api) -> Generator[recipe_test_api.TestData, None, None]:
  def test(name, *args, status, step_name='result', retcode=0, **kwargs):
    res = api.test(name, *args, status=status, **kwargs)

    if status in ('FAILURE', 'INFRA_FAILURE'):
      res += api.post_process(post_process.DoesNotRun, 'is ok')
      res += api.post_process(post_process.DoesNotRun, 'step succeeded')
      if step_name:
        res += api.post_process(post_process.MustRun, step_name)
    else:
      res += api.post_process(post_process.MustRun, 'is ok')
      res += api.post_process(post_process.MustRun, 'step succeeded')

    res += api.step_data('step', retcode=retcode)
    res += api.properties(
        properties_pb2.ResultInputProps(step_name=step_name, **kwargs))

    if kwargs.get('exception', False):
        res += api.expect_exception('ResultTestError')

    res += api.post_process(post_process.DropExpectation)

    return res

  yield test('success', status='SUCCESS')
  yield test('failure', status='FAILURE', retcode=1)
  yield test('infra', status='INFRA_FAILURE', retcode=1, infra_steps=True)
  yield test('exception', exception=True, status='INFRA_FAILURE')
  yield test('noname', step_name=None, exception=True, status='INFRA_FAILURE')
