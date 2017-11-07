# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'buildbucket',
]


def RunSteps(api):
  api.buildbucket.get_build('9016911228971028736')


def GenTests(api):
  yield (
      api.test('basic') +
      api.buildbucket.simulated_buildbucket_output(None)
  )
