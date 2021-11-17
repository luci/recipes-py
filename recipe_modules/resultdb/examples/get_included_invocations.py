# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    'recipe_engine/assertions',
    'resultdb',
]


def RunSteps(api):
  sub_invs = api.resultdb.get_included_invocations(
      inv_name='invocations/build-8831400474790691137')
  api.assertions.assertIn('inv1', sub_invs)
  api.assertions.assertIn('inv2', sub_invs)
  api.assertions.assertEqual(2, len(sub_invs))


def GenTests(api):
  yield api.test(
      'basic',
      api.resultdb.get_included_invocations(['inv1', 'inv2']),
      api.post_process(DropExpectation),
  )
