# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Test to assert that sort_keys=False preserves insertion order."""

import string

BACKWARDS = ''.join(reversed(string.ascii_lowercase))


DEPS = [
  'json',
  'step',
]

def RunSteps(api):
  d = {}
  for i, letter in enumerate(BACKWARDS):
    d[letter] = i

  api.step('sorted', ['echo', api.json.input(d)])
  api.step('unsorted', ['echo', api.json.input(d, sort_keys=False)])

def GenTests(api):
  # We assert here that 'sorted' is in alphabetical order and 'unsorted' is in
  # reverse order. If python is randomizing dictionary order (which it does not
  # after python 3.7), then this test should catch it.
  def check_order(check, steps, stepname, alphabet):
    step = steps[stepname]
    filtered = ''.join(letter for letter in step.cmd[1] if letter in alphabet)
    check(filtered == alphabet)

  yield api.test(
      'basic',
      api.post_process(check_order, 'sorted', string.ascii_lowercase),
      api.post_process(check_order, 'unsorted', BACKWARDS),
  )
