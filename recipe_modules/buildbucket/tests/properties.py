# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'buildbucket',
  'properties',
  'step',
]


def RunSteps(api):
  api.step('properties', [])
  api.step.active_result.presentation.logs['details'] = [
    'properties: %r' % (api.buildbucket.properties,)
  ]


def GenTests(api):
  yield api.test('empty')

  yield (
      api.test('structured') +
      api.properties(
          buildbucket={'build': {'tags': [
              'buildset:patch/rietveld/cr.chromium.org/123/10001']}})
  )

  yield (
      api.test('serialized') +
      api.properties(
          buildbucket='{"build": {"tags": ['
              '"buildset:patch/rietveld/cr.chromium.org/123/10001"]}}')
  )
