# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.tricium.data import Data

DEPS = [
  'tricium',
]

def RunSteps(api):
  api.tricium._comments_num_limit = 5  # reset the limit to 5 for testing.
  for i in range(10):
    api.tricium.add_comment('test', 'test message', 'path/to/file_%d' % i)

  api.tricium.write_comments()


def GenTests(api):
  yield (api.test('basic') +
      api.post_process(
        post_process.PropertyEquals, 'tricium',
        json_format.MessageToJson(Data.Results(comments=[
          Data.Comment(
              category='test',
              message='test message',
              path='path/to/file_%d' % i)
          for i in range(5)]), indent=0)) +
      api.post_process(post_process.DropExpectation))
