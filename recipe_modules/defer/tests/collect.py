# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib
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

PROPERTIES = properties_pb2.CollectInputProps


class CollectTestError(Exception):
    pass



def RunSteps(api, props):

  def step(i):
    api.step(f'step {i}', ['cmd'])
    if props.exception:
      raise CollectTestError()

  deferred = []
  for i in range(5):
    with api.context(infra_steps=bool(i % 2)):
      deferred.append(api.defer(step, i))
  api.step.empty('done running steps')
  api.defer.collect(deferred, step_name=props.step_name or None)
  api.step.empty('all steps succeeded')


def GenTests(api) -> Generator[recipe_test_api.TestData, None, None]:
  def test(name, *args, status, exception=False, step_name='collect', **kwargs):
    res = api.test(name, *args, status=status, **kwargs)
    res += api.properties(properties_pb2.CollectInputProps(step_name=step_name,
                                                           exception=exception))

    res += api.post_process(post_process.MustRun, 'done running steps')

    if status in ('FAILURE', 'INFRA_FAILURE'):
      res += api.post_process(post_process.DoesNotRun, 'all steps succeeded')
      if step_name:
        res += api.post_process(post_process.MustRun, step_name)
    else:
      res += api.post_process(post_process.MustRun, 'all steps succeeded')

    if exception:
      res += api.expect_exception('CollectTestError')

    res += api.post_process(post_process.DropExpectation)

    return res

  def failure(n) -> step_data.StepData:
    return api.step_data(f'step {n}', retcode=1)


  yield test('success', status='SUCCESS')

  yield test('fail_0', failure(0), status='FAILURE')
  yield test('infra_fail_3', failure(3), status='INFRA_FAILURE')

  yield test('multi_fail', failure(0), failure(2), status='FAILURE')
  yield test('multi_infra_fail', failure(0), failure(3), status='INFRA_FAILURE')

  yield test('all_fail', *[failure(x) for x in range(5)],
             status='INFRA_FAILURE')

  yield test('exception', exception=True, status='INFRA_FAILURE')

  yield test('noname', step_name=None, exception=True, status='INFRA_FAILURE')
