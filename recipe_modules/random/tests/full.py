# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  "random",
  "step",
]


def RunSteps(api):
  my_list = list(range(10))
  api.random.shuffle(my_list)
  api.step('echo list', ['echo', ', '.join(map(str, my_list))])

  my_randrange = [api.random.randrange(1000, 15000000, 3) for _ in range(10)]
  api.step('echo randrange', ['foo'] + list(map(str, my_randrange)))


def GenTests(api):
  yield api.test("basic")

  yield api.test("reseed") + api.random.seed(4321)
