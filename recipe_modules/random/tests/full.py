# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  "random",
  "step",
]


def RunSteps(api):
  my_list = list(range(10))
  # Use a specific random number generator to ensure consistency between Python
  # 2 and 3.
  api.random.shuffle(my_list, api.random.random)
  api.step('echo list', ['echo', ', '.join(map(str, my_list))])


def GenTests(api):
  yield api.test("basic")

  yield api.test("reseed") + api.random.seed(4321)
