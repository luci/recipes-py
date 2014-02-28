# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'json',
  'step',
  'step_history',
]


def GenSteps(api):
  yield api.step('echo', ['echo', '[1, 2, 3]'],
      stdout=api.json.output())
  assert api.step_history.last_step().stdout == [1, 2, 3]


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo', stdout=api.json.output([1, 2, 3])))
