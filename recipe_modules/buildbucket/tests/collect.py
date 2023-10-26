# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'buildbucket',
  'properties',
  'step',
]


def RunSteps(api):
  api.buildbucket.collect_build(
      9016911228971028736, interval=30, step_name='collect1',
      mirror_status=True,
      cost=api.step.ResourceCost(memory=10))
  api.buildbucket.collect_builds(
      [9016911228971028737, 123456789012345678], timeout=600,
      raise_if_unsuccessful=api.properties.get('raise_if_unsuccessful', False),
      mirror_status=True, fields=['builder'])


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'with mocking',
      api.buildbucket.simulated_collect_output(
        [
          api.buildbucket.ci_build_message(
              build_id=9016911228971028736, status='INFRA_FAILURE'),
        ],
        step_name='collect1'),
      api.buildbucket.simulated_collect_output([
        api.buildbucket.try_build_message(
            build_id=9016911228971028737, status='SUCCESS'),
        api.buildbucket.ci_build_message(
            build_id=123456789012345678, status='FAILURE'),
      ]),
  )

  yield api.test(
      'with mocking and failure raising',
      api.properties(raise_if_unsuccessful=True),
      api.buildbucket.simulated_collect_output(
        [
          api.buildbucket.ci_build_message(
              build_id=9016911228971028736, status='INFRA_FAILURE'),
        ],
        step_name='collect1'),
      api.buildbucket.simulated_collect_output([
        api.buildbucket.try_build_message(
            build_id=9016911228971028737, status='SUCCESS'),
        api.buildbucket.ci_build_message(
            build_id=123456789012345678, status='FAILURE'),
      ]),
      status = 'INFRA_FAILURE',
  )
