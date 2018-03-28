# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'buildbucket',
  'properties',
  'step',
]


def RunSteps(api):
  api.step('build_id', ['dummy']).presentation.properties['result'] = {
    'build_input': api.buildbucket.build_input,
  }


def GenTests(api):
  yield api.test('no buildsets')

  yield (api.test('empty buildset') +
         api.properties(
             buildbucket={
              'build': {
                'tags': ['buildset:'],
             }}))

  yield (api.test('unknown format') +
         api.properties(
             buildbucket={
              'build': {
                'tags': ['buildset:x'],
             }}))

  yield (api.test('gerrit change') +
         api.properties(
             buildbucket={
              'build': {
                'tags': [
                  ('buildset:patch/gerrit/'
                    'chromium-review.googlesource.com/1/2'),
                ],
             }}))

  yield (api.test('gitiles commit') +
         api.properties(
             buildbucket={
              'build': {
                'project': 'test-project',
                'bucket': 'luci.test-project.test-bucket',
                'tags': [
                  ('buildset:commit/gitiles/'
                    'chromium.googlesource.com/chromium/src/+/'
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
                ],
             }}))

  yield (api.test('gitiles commit, invalid') +
         api.properties(
             buildbucket={
              'build': {
                'project': 'test-project',
                'bucket': 'luci.test-project.test-bucket',
                'tags': ['buildset:commit/gitiles/a/b/c/d'],
             }}))
