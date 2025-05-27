# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that daemons that hang on to STDOUT can't cause the engine to hang."""

from __future__ import annotations

DEPS = [
  'platform',
  'step',
]


def RunSteps(api):
  api.step(
      'bad daemon',
      ['python3',
       api.resource('win.py' if api.platform.is_win else 'unix.py')])


def GenTests(api):
  yield api.test('basic')
  yield api.test('basic_win') + api.platform(name='win', bits=64)
