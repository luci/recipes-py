# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

DEPS = ["path"]


def RunSteps(api):
  try:
    api.path['something'] = 'hello'
    # pragma: no cover
    assert False, "able to assign string to path?"  # pragma: no cover
  except ValueError as ex:
    assert "other than a Path" in str(ex), str(ex)

  try:
    api.path['something'] = api.path['start_dir'].join('coolstuff')
    # pragma: no cover
    assert False, "able to assign path to non-dynamic path?"  # pragma: no cover
  except ValueError as ex:
    assert "declare dynamic path" in str(ex), str(ex)

  # OK!
  api.path['checkout'] = api.path['start_dir'].join('coolstuff')

  # Can re-set to the same thing
  api.path['checkout'] = api.path['start_dir'].join('coolstuff')

  try:
    # Setting a new value is not allowed
    api.path['checkout'] = api.path['start_dir'].join('neatstuff')
    assert False, "able to set a dynamic path twice?"  # pragma: no cover
  except ValueError as ex:
    assert "can only be set once" in str(ex), str(ex)


def GenTests(api):
  yield api.test('basic', api.post_process(DropExpectation))
