# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "random",
  "step",
]


def RunSteps(api):
  my_list = range(10)
  api.random.shuffle(my_list)
  api.step('echo list', ['echo', ', '.join(map(str, my_list))])


def GenTests(api):
  yield api.test("basic")

  yield api.test("reseed") + api.random.seed(4321)
