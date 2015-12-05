# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'path',
  'platform',
  'properties',
  'step',
]

from recipe_engine.config_types import Path

def RunSteps(api):
  api.path.set_config('example')

  api.step('step1', ['/bin/echo', str(api.path['slave_build'].join('foo'))])

  # module.resource(...) demo.
  api.step('print resource',
           ['echo', api.path.resource('dir', 'file.py')])

  # module.package_dir() demo.
  api.step('print package dir',
           ['echo', api.path.package_resource('dir', 'file.py')])

  # Global dynamic paths (see config.py example for declaration):
  dynamic_path = Path('[BORTS]', 'jerky')

  assert 'borts' not in api.path
  api.path['borts'] = api.path['slave_build'].join('borts')
  assert 'borts' in api.path

  api.step('borts path', ['/bin/echo', dynamic_path])

  # Methods from python os.path are available via api.path.
  # For testing, we asserted that this file existed in the test description
  # below.
  assert api.path.exists(api.path['slave_build'])

  temp_dir = api.path.mkdtemp('kawaab')
  assert api.path.exists(temp_dir)

  file_path = api.path['slave_build'].join('new_file')
  abspath = api.path.abspath(file_path)
  api.path.assert_absolute(abspath)

  api.step('touch me', ['touch', api.path.abspath(file_path)])
  # Assert for testing that a file exists.
  api.path.mock_add_paths(file_path)
  assert api.path.exists(file_path)



def GenTests(api):
  for platform in ('linux', 'win', 'mac'):
    yield (api.test(platform) + api.platform.name(platform) +
           # Test when a file already exists
           api.path.exists(api.path['slave_build']))

  # We have support for chromium swarming built in to the engine for some
  # reason. TODO(phajdan.jr) remove it.
  yield (api.test('linux_swarming') +
         api.properties(path_config='swarming') +
         api.path.exists(api.path['slave_build']))
