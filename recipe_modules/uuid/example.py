# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'step',
  'uuid',
]


def RunSteps(api):
  uuid = api.uuid.random()
  api.step('echo', ['echo', str(uuid)])


def GenTests(api):
  yield api.test('basic')
