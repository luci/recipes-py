# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from PB.tricium.data import Data
from PB.recipe_modules.recipe_engine.tricium.tests.enforce_comments_num_limit import InputProps

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'assertions',
    'properties',
    'proto',
    'tricium',
]

PROPERTIES = InputProps


def RunSteps(api, props):
  api.tricium._comments_num_limit = 5  # reset the limit to 5 for testing.
  for i in range(10):
    api.tricium.add_comment('test', 'test message', 'path/to/file_%d' % i)

  step = api.tricium.write_comments()
  result = step.presentation.properties.get('tricium')
  expected = api.proto.encode(
      props.expected_results,
      'JSONPB',
      indent=0,
      preserving_proto_field_name=False)
  api.assertions.assertEqual(result, expected)


def GenTests(api):
  yield (api.test('basic') + api.properties(
      InputProps(
          expected_results=Data.Results(comments=[
              Data.Comment(
                  category='test',
                  message='test message',
                  path='path/to/file_%d' % i) for i in range(5)
          ]))) + api.post_process(post_process.DropExpectation))
