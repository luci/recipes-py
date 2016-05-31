# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'path',
  'platform',
  'properties',
  'step',
]

from recipe_engine.config_types import Path

def RunSteps(api):
  api.step('step1', ['/bin/echo', str(api.path['tmp_base'].join('foo'))])

  # module.resource(...) demo.
  api.step('print resource',
           ['echo', api.path.resource('dir', 'file.py')])

  # module.package_repo_resource() demo.
  api.step('print package dir',
           ['echo', api.path.package_repo_resource('dir', 'file.py')])

  assert 'checkout' not in api.path
  api.path['checkout'] = api.path['tmp_base'].join('checkout')
  assert 'checkout' in api.path

  # Global dynamic paths (see config.py example for declaration):
  dynamic_path = api.path['checkout'].join('jerky')
  api.step('checkout path', ['/bin/echo', dynamic_path])

  # Methods from python os.path are available via api.path.
  # For testing, we asserted that this file existed in the test description
  # below.
  assert api.path.exists(api.path['tmp_base'])

  temp_dir = api.path.mkdtemp('kawaab')
  assert api.path.exists(temp_dir)

  file_path = api.path['tmp_base'].join('new_file')
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
           api.path.exists(api.path['tmp_base']))

    # We have support for chromium swarming built in to the engine for some
    # reason. TODO(phajdan.jr) remove it.
    yield (api.test('%s_swarming' % platform) +
           api.platform.name(platform) +
           api.properties(path_config='swarming') +
           api.path.exists(api.path['tmp_base']))

    yield (api.test('%s_kitchen' % platform) +
           api.platform.name(platform) +
           api.properties(path_config='kitchen') +
           api.path.exists(api.path['tmp_base']))
