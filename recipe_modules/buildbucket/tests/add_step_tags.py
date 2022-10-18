# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'buildbucket',
  'step',
]


def RunSteps(api):
  step = api.step('hostname', ['echo', api.buildbucket.host])
  step.presentation.tags[u'k1'] = u'v1'
  step.presentation.tags[u'k2'] = u'v2'

def GenTests(api):
  def assert_pairs(check, steps):
    check(steps["hostname"].tags["k1"] == "v1")
    check(steps["hostname"].tags["k2"] == "v2")

  yield api.test('basic') + api.post_check(assert_pairs)
