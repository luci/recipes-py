# -*- coding: utf-8 -*-
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'properties',
    'step',
]

def RunSteps(api):
  result = api.step(
      'trigger some junk',
      cmd=['echo', 'hi'],
  )
  result.presentation.logs['thing'] = [
      u'hiiiii 😀…' , #This is valid, and should be displayed
      '\xe2', # This is invalid, and should show up as an invalid character
  ]

def GenTests(api):
  yield api.test('basic')
