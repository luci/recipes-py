# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'assertions',
    'cv',
    'properties',
    'step',
]


def RunSteps(api):
  if 'raises' in api.properties:
    with api.assertions.assertRaises(api.cv.CQInactive):
      api.cv.experimental
    with api.assertions.assertRaises(api.cv.CQInactive):
      api.cv.top_level
    return

  api.assertions.assertEqual(api.cv.experimental, 'expected_experimental'
                             in api.properties)
  api.assertions.assertEqual(api.cv.top_level, 'expected_top_level'
                             in api.properties)


def GenTests(api):
  yield (api.test('default') + api.cv(run_mode=api.cv.FULL_RUN) +
         api.properties(expected_top_level=True) +
         api.post_process(post_process.DropExpectation))
  yield (api.test('indirect and experimental') +
         api.cv(run_mode=api.cv.FULL_RUN, top_level=False, experimental=True) +
         api.properties(expected_experimental=True) +
         api.post_process(post_process.DropExpectation))
  yield (api.test('not a CQ run') + api.properties(raises=True) +
         api.post_process(post_process.DropExpectation))
