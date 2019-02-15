# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that recipes have access to names, resources and their repo."""

DEPS = [
  'path',
  'python',
  'step',
]

def RunSteps(api):
  api.step('recipe_name', ['echo', 'recipe name is', api.name])
  api.python('some_resource', api.resource('hello.py'))
  api.step('repo_root', ['echo', api.repo_resource('file', 'path')])

def GenTests(api):
  yield api.test('basic')
