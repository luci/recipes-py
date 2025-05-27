# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This tests metadata features of the Future object."""

from __future__ import annotations

DEPS = [
  'futures',
  'step',
]


def RunSteps(api):
  # We get a default name
  fut = api.futures.spawn(api.step, 'default_name', None)
  assert fut.name == 'Future-0'
  assert fut.meta is None

  # We can set a name
  fut = api.futures.spawn(api.step, 'custom_name', None, __name='custom string')
  assert fut.name == 'custom string'
  assert fut.meta is None

  # We can set metadata
  fut = api.futures.spawn(api.step, 'meta', None, __meta={'hi': 'there'})
  assert fut.name == 'Future-2'
  assert fut.meta == {'hi': 'there'}

  # Can mutate meta
  fut.meta['narf'] = 'poit'
  assert fut.meta == {'hi': 'there', 'narf': 'poit'}

  # Cannot assign to meta
  try:
    fut.meta = 'hamster'
    assert False, 'incorrectly assigned'  # pragma: no cover
  except:
    pass


def GenTests(api):
  yield api.test('basic')
