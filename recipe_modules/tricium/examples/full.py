# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = ['tricium', 'properties']

PROPERTIES = {
    'trigger_type_error': Property(kind=bool, default=False),
}


def RunSteps(api, trigger_type_error):
  for filename in api.tricium.paths:
    api.tricium.add_comment('test', 'test message', filename)
    # Check that duplicate comments aren't entered.
    api.tricium.add_comment('test', 'test message', filename)

  suggestions = [{'description': 'please fix this'}]

  api.tricium.repository
  api.tricium.ref
  api.tricium.add_comment(
      'another',
      'another test message',
      'path/to/file/2',
      start_char='10' if trigger_type_error else 10,
      end_char=20,
      suggestions=suggestions,
  )

  api.tricium.write_comments()
  api.tricium.write_comments(dump=True)


def GenTests(api):
  yield (api.test('basic') + api.properties(
      repository='https://chromium.googlesource.com/luci/recipes-py',
      ref='refs/changes/99/999999/9',
      paths=['path/to/file']))
  yield (api.test('type_error') + api.properties(trigger_type_error=True) +
         api.expect_exception('TypeError') + api.post_process(post_process.DropExpectation))
