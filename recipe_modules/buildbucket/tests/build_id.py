# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'buildbucket',
  'properties',
  'step',
]


def RunSteps(api):
  api.step('build_id', ['echo', '%r' % (api.buildbucket.build_id, )])


def GenTests(api):
  yield api.test('empty')

  yield (
      api.test('with_build') +
      api.properties(buildbucket={'build': {'id': '123456789'}})
  )
