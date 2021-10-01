# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


"""This test serves to demonstrate that the ModuleInjectionSite object on
recipe modules (i.e. the `.m`) also contains a reference to the module which
owns it.

This was implemented to aid in refactoring some recipes (crbug.com/782142).
"""

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  "recipe_engine/path",
  "step",
]

def RunSteps(api):
  api.step("echo useless thing", ["echo", api.path.m.path.join("a", "b")])

def GenTests(api):
  yield api.test("basic")
