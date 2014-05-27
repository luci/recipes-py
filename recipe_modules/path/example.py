# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'path',
  'platform',
  'step',
  'step_history',
]


def GenSteps(api):
  yield (api.step('step1',
                  ['/bin/echo', str(api.path['slave_build'].join('foo'))]))

  # listdir demo.
  yield api.path.listdir('fake dir', '/fake/dir')
  for element in api.step_history.last_step().json.output:
    yield api.step('manipulate %s' % str(element), ['some', 'command'])

  # mkdtemp demo.
  for prefix in ('prefix_a', 'prefix_b'):
    # Create temp dir.
    temp_dir = api.path.mkdtemp(prefix)
    assert api.path.exists(temp_dir)
    # Make |temp_dir| surface in expectation files.
    yield api.step('print %s' % prefix, ['echo', temp_dir])

  # module.resource(...) demo.
  yield api.step('print resource',
                 ['echo', api.path.resource('dir', 'file.py')])

  # rmwildcard demo
  yield api.path.rmwildcard('*.o', api.path['slave_build'])


def GenTests(api):
  # This line is for code coverage.
  api.path['slave_build'].join('foo')

  for platform in ('linux', 'win', 'mac'):
    yield api.test(platform) + api.platform.name(platform)
