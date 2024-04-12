# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Test to cover legacy aspects of PathTestApi."""

from recipe_engine.post_process import DropExpectation

DEPS = ['path']

GETITEM_NAMES = [
    'cache',
    'cleanup',
    'home',
    'start_dir',
    'tmp_base',
]


def RunSteps(api):
  for name in GETITEM_NAMES:
    p = api.path.get(name) / 'file'
    assert api.path.exists(p), p

  api.path.checkout_dir = api.path.start_dir / 'somedir'
  assert api.path.exists(api.path.get('checkout') / 'file')


def GenTests(api):
  def base_path(name):
    if not name.endswith('_dir'):
      name += '_dir'
    return getattr(api.path, name)

  paths = [base_path(name).join('file') for name in GETITEM_NAMES]
  paths.append(api.path.checkout_dir.join('file'))

  yield api.test(
      'basic',
      api.path.exists(*paths),
      api.post_process(DropExpectation),
  )
