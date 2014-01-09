# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['properties', 'step']

def GenSteps(api):
  yield api.step('echo', ['echo'] + [repr(api.properties['test_prop'])])

def GenTests(api):
  yield api.test('basic') + api.properties(
    test_prop={'key': 'value'})
  yield api.test('lists') + api.properties(
    test_prop={'key': ['value', ['value']]})
  yield api.test('dicts') + api.properties(
    test_prop={'key': {'key': 'value', 'other_key': {'key': 'value'}}})

