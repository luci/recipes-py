# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'tempfile',
]

def RunSteps(api):
  with api.tempfile.temp_dir('foo'):
    pass


def GenTests(api):
  yield api.test('basic')
