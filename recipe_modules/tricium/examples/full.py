# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'tricium',
  'properties'
]


def RunSteps(api):
  for filename in api.tricium.paths:
    api.tricium.add_comment('test', 'test message', filename)
    # Check that duplicate comments aren't entered.
    api.tricium.add_comment('test', 'test message', filename)
  
  api.tricium.repository
  api.tricium.ref
  api.tricium.add_comment(
    'another',
    'another test message',
    'path/to/file/2',
    start_char=10,
    end_char=20
  )

  api.tricium.write_comments()


def GenTests(api):
  yield (api.test('basic') + api.properties(
    repository='https://chromium.googlesource.com/luci/recipes-py',
    ref='refs/changes/99/999999/9',
    paths=['path/to/file']))
