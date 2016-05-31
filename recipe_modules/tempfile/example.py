# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'tempfile',
]

def RunSteps(api):
  with api.tempfile.temp_dir('foo'):
    pass


def GenTests(api):
  yield api.test('basic')
