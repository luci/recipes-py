# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'step',
]

def RunSteps(api):
  ran_both = False
  try:
    with api.step.defer_results():
      api.step("testa", ["echo", "testa"])
      api.step("testb", ["echo", "testb"])
      ran_both = True
  finally:
    assert ran_both


def GenTests(api):
  yield api.test('basic')

  yield (
      api.test('one_fail') +
      api.step_data('testa', retcode=1)
    )
