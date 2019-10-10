# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Launches multiple builds at the same revision."""

from recipe_engine.config import List
from recipe_engine.config import Single
from recipe_engine.recipe_api import Property


DEPS = [
    'buildbucket',
    'properties',
]

PROPERTIES = {
    'build_requests': Property(
        kind=List(dict),
        help='List of params to buildbucket.schedule_request for builds'
        ' to trigger.'),
    'collect_builds': Property(
        kind=Single(bool),
        default=False,
        help='Whether to wait for child builds and surface failures.'),
}


def RunSteps(api, build_requests, collect_builds):
  builds_to_schedule = []
  for params in build_requests:
    builds_to_schedule.append(api.buildbucket.schedule_request(**params))
  if collect_builds:
      api.buildbucket.run(builds_to_schedule, raise_if_unsuccessful=True)
  else:
      api.buildbucket.schedule(builds_to_schedule)


def GenTests(api):
  yield (
      api.test('basic') +
      api.buildbucket.ci_build(priority=50) +
      api.properties(
          build_requests=[
              {
                  'builder': 'linux',
                  'project': 'chromium',
                  'bucket': 'ci',
              },
              {
                  'builder': 'win',
                  'project': 'chromium',
                  'bucket': 'ci',
                  'priority': 30,
              },
              {
                  'builder': 'mac',
                  'project': 'chromium',
                  'bucket': 'ci',
                  'priority': None,
              },
          ])
  )
  yield (
      api.test('collect') +
      api.properties(
          build_requests=[
              {
                  'builder': 'linux',
                  'project': 'chromium',
                  'bucket': 'ci',
              },
              {
                  'builder': 'win',
                  'project': 'chromium',
                  'bucket': 'ci',
              },
              {
                  'builder': 'mac',
                  'project': 'chromium',
                  'bucket': 'ci',
              },
          ],
          collect_builds=True,
      )
  )
