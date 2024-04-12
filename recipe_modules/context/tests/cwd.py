# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "context",
  "path",
  "step",
]

def RunSteps(api):
  api.step('no cwd', ['echo', 'hello'])

  with api.context(cwd=api.path.start_dir.join('subdir')):
    api.step('with cwd', ['echo', 'hello', 'subdir'])

  with api.context(cwd=None):
    api.step('with cwd=None', ['echo', 'hello', 'subdir'])

def GenTests(api):
  yield api.test('basic')
