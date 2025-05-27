# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api
from recipe_engine.post_process import DropExpectation

DEPS = ['path']


@recipe_api.ignore_warnings('recipe_engine/CHECKOUT_DIR_DEPRECATED')
def RunSteps(api):
  try:
    api.path.checkout_dir = 'hello'
    assert False, 'able to assign string to path?'  # pragma: no cover
  except ValueError as ex:
    assert 'called with bad type' in str(ex), str(ex)

  try:
    # Note - legacy api.path.get('checkout') is the only way to get a dynamic
    # checkout path before assignment to checkout_dir.
    api.path.checkout_dir = api.path.checkout_dir / 'something'
    assert False, 'able to assign string to path?'  # pragma: no cover
  except ValueError as ex:
    assert 'cannot be rooted in checkout_dir' in str(ex), str(ex)

  # OK!
  api.path.checkout_dir = api.path.start_dir / 'coolstuff'

  # Can re-set to the same thing
  api.path.checkout_dir = api.path.start_dir / 'coolstuff'

  try:
    # Setting a new value is not allowed
    api.path.checkout_dir = api.path.start_dir / 'neatstuff'
    assert False, 'able to set a dynamic path twice?'  # pragma: no cover
  except ValueError as ex:
    assert 'can only be set once' in str(ex), str(ex)


def GenTests(api):
  yield api.test('basic', api.post_process(DropExpectation))
