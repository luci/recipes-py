# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api
from recipe_engine.post_process import DropExpectation

DEPS = ['path']


@recipe_api.ignore_warnings('recipe_engine/CHECKOUT_DIR_DEPRECATED')
def RunSteps(api):
  assert not api.path.exists(api.path.start_dir / 'does not exist')
  assert not api.path.isfile(api.path.start_dir / 'does not exist')
  assert not api.path.isdir(api.path.start_dir / 'does not exist')

  assert api.path.exists(api.path.start_dir / 'a file')
  assert api.path.isfile(api.path.start_dir / 'a file')
  assert not api.path.isdir(api.path.start_dir / 'a file')

  assert api.path.exists(api.path.start_dir / 'a dir')
  assert not api.path.isfile(api.path.start_dir / 'a dir')
  assert api.path.isdir(api.path.start_dir / 'a dir')

  # Our PathTestApi allows us to mock the existence of paths in the checkout
  # directory. However, the checkout directory still must be set before this
  # check is done.
  api.path.checkout_dir = api.path.cache_dir / 'builder' / 'src'
  assert api.path.exists(api.path.checkout_dir / 'somefile')


def GenTests(api):
  yield api.test(
      'basic',
      api.path.files_exist(
          api.path.start_dir / 'a file',
          api.path.checkout_dir / 'somefile',
      ),
      api.path.dirs_exist(api.path.start_dir / 'a dir'),
      api.post_process(DropExpectation),
  )
