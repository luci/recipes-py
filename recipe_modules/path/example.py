# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'path',
  'platform',
  'step',
]


def GenSteps(api):
  # New way of doing things
  yield (api.step('step1',
                  ['/bin/echo', str(api.path['slave_build'].join('foo'))]))
  # Deprecated way of doing things.
  # TODO(pgervais,crbug.com/323280) remove this api
  yield (api.step('step2',
                  ['/bin/echo', str(api.path.slave_build('foo'))]))

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


def GenTests(api):
  # These two lines are for code coverage.
  api.path.slave_build('foo')  # TODO(pgervais,crbug.com/323280) remove this api
  api.path['slave_build'].join('foo')

  for platform in ('linux', 'win', 'mac'):
    yield api.test(platform) + api.platform.name(platform)
