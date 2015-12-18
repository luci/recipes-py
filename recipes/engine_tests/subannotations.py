# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['step']

def RunSteps(api):
  api.step('Dont subannotate me', ['echo', '@@@BUILD_STEP@steppy@@@'])
  api.step('Subannotate me', ['echo', '@@@BUILD_STEP@pippy@@@'], allow_subannotations=True)

def GenTests(api):
  yield api.test('basic')
