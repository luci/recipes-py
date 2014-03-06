# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'step',
  'time',
]


def GenSteps(api):
  now = api.time.time()
  yield api.step('echo', ['echo', str(now)])


def GenTests(api):
  yield api.test('defaults')
  yield api.test('seed_and_step') + api.time.seed(123) + api.time.step(2)
