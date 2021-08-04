# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = ['tricium', 'properties']

PROPERTIES = {
    'case': Property(kind=str),
}

_CASES = {
    'bad start_line': dict(start_line=-1),
    'file level comment: end_line': dict(start_line=0, end_line=1),
    'file level comment: start_char': dict(start_line=0, start_char=1),
    'file level comment: end_char': dict(start_line=0, end_char=1),
    'end_line': dict(start_line=2, end_line=1),
    'start_char': dict(start_line=1, start_char=-1, end_line=2),
    'end_char': dict(start_line=1, start_char=1, end_line=2, end_char=-1),
    'wrong-range': dict(start_line=5, start_char=5, end_line=5, end_char=4),
}


def RunSteps(api, case):
  # Set valid default.
  kwargs = dict(
      category='test',
      message='msg',
      path='path/to/file',
  )
  kwargs.update(_CASES[case])
  api.tricium.add_comment(**kwargs)


def GenTests(api):
  for name in _CASES:
    yield api.test(name, api.properties(case=name),
                   api.expect_exception(ValueError.__name__),
                   api.post_process(post_process.DropExpectation))
