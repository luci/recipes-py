# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

DEPS = ['path']


def RunSteps(api):
  try:
    api.path.checkout_dir = 'hello'
    assert False, 'able to assign string to path?'  # pragma: no cover
  except ValueError as ex:
    assert 'called with bad type' in str(ex), str(ex)

  try:
    # Note - legacy api.path.get('checkout') is the only way to get a dynamic
    # checkout path before assignment to checkout_dir.
    api.path.checkout_dir = api.path.get('checkout') / 'something'
    assert False, 'able to assign string to path?'  # pragma: no cover
  except ValueError as ex:
    assert 'cannot be rooted in checkout_dir' in str(ex), str(ex)

  try:
    api.path['something'] = api.path.start_dir / 'coolstuff'
    assert False, 'able to assign path to non-dynamic path?'  # pragma: no cover
  except ValueError as ex:
    assert 'The only valid dynamic path value is `checkout`' in str(ex), str(ex)

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
