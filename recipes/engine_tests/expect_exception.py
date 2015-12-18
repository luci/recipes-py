# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

DEPS = [
  'step',
]

def RunSteps(api):
  raise TypeError("BAD DOGE")

def GenTests(api):
  yield (
    api.test('basic') +
    api.expect_exception('TypeError')
  )
