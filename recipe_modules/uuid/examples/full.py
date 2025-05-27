# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'recipe_engine/step',
  'uuid',
]


def RunSteps(api):
  api.step('echo', ['echo', api.uuid.random()])


def GenTests(api):
  yield api.test('basic')
