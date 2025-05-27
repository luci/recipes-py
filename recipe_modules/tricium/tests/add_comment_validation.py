# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = ['buildbucket', 'tricium', 'properties']

PROPERTIES = {
    'case': Property(kind=str),
}

_BAD_CASES = {
    'bad start_line':
        dict(start_line=-1),
    'file level comment: end_line':
        dict(start_line=0, end_line=1),
    'file level comment: start_char':
        dict(start_line=0, start_char=1),
    'file level comment: end_char':
        dict(start_line=0, end_char=1),
    'end_line':
        dict(start_line=2, end_line=1),
    'start_char':
        dict(start_line=1, start_char=-1, end_line=2),
    'end_char':
        dict(start_line=1, start_char=1, end_line=2, end_char=-1),
    'wrong-range':
        dict(start_line=5, start_char=5, end_line=5, end_char=5),
    'absolute path':
        dict(start_line=3, end_line=3, path="/usr/home/me/checkout/foo.txt"),
}
_OK_CASES = {
    'exactly 1 char': dict(start_line=5, start_char=5, end_line=5, end_char=6),
    'end of 1 line': dict(start_line=5, start_char=5, end_line=6, end_char=1),
    'just 1 entire line': dict(start_line=3, end_line=3),
    'several entire lines': dict(start_line=3, end_line=5),
}

def RunSteps(api, case):
  # Set valid default.
  kwargs = dict(
      category='test',
      message='msg',
      path='path/to/file',
  )
  if case in _BAD_CASES:
    kwargs.update(_BAD_CASES[case])
  elif case in _OK_CASES:
    kwargs.update(_OK_CASES[case])
  else:  # pragma: nocover
    assert 'unknown case', case
  api.tricium.add_comment(**kwargs)

  # ensure that it adds objects to both
  assert api.tricium._comments
  assert api.tricium._findings


def GenTests(api):
  for name in _BAD_CASES:
    yield api.test(name, api.properties(case=name),
                   api.expect_exception(ValueError.__name__),
                   api.post_process(post_process.DropExpectation),
                   api.buildbucket.try_build(project='chrome'))
  for name in _OK_CASES:
    yield api.test(name, api.properties(case=name),
                   api.post_process(post_process.DropExpectation),
                   api.buildbucket.try_build(project='chrome'))
