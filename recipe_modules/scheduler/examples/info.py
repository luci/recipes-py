# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating reading/mocking scheduler host."""

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'scheduler',
  'step',
]

def RunSteps(api):
  step_res = api.step(name='host', cmd=None)
  step_res.presentation.logs['info'] = [
      api.scheduler.host,
      '%s' % api.scheduler.job_id,
      '%s' % api.scheduler.invocation_id
  ]

def GenTests(api):
  yield (
    api.test('unset')
  )
  yield (
    api.test('set') +
    api.scheduler(
      hostname='scheduler.example.com',
      job_id='some/job',
      invocation_id=12345,
    )
  )
