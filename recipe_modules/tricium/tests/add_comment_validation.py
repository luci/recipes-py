# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.tricium.tests import add_comment_validation as add_comment_validation_pb
from recipe_engine import post_process

DEPS = ['buildbucket', 'tricium', 'properties']

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  string case = 1;
}
"""

PROPERTIES = add_comment_validation_pb.InputProperties

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

def RunSteps(api, props: add_comment_validation_pb.InputProperties):
  # Set valid default.
  kwargs = dict(
      category='test',
      message='msg',
      path='path/to/file',
  )
  if props.case in _BAD_CASES:
    kwargs.update(_BAD_CASES[props.case])
  elif props.case in _OK_CASES:
    kwargs.update(_OK_CASES[props.case])
  else:  # pragma: nocover
    assert 'unknown case', props.case
  api.tricium.add_comment(**kwargs)

  # ensure that it adds objects to both
  assert api.tricium._comments
  assert api.tricium._findings


def GenTests(api):
  for name in _BAD_CASES:
    yield api.test(
        name,
        api.properties(add_comment_validation_pb.InputProperties(case=name)),
        api.expect_exception(ValueError.__name__),
        api.post_process(post_process.DropExpectation),
        api.buildbucket.try_build(project='chrome'))
  for name in _OK_CASES:
    yield api.test(
        name,
        api.properties(add_comment_validation_pb.InputProperties(case=name)),
        api.post_process(post_process.DropExpectation),
        api.buildbucket.try_build(project='chrome'))
