# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "context",
  "path",
  "step",
]


def RunSteps(api):
  api.step('no nesting', ['echo', 'hello'])

  with api.context(increment_nest_level=True):
    api.step('nested', ['echo', 'hello'])

  # typically, however, folks should use api.step.nest, as noted in the docs for
  # context.
  with api.step.nest('proper nesting'):
    api.step('real nested', ['echo', 'hello'])

  try:
    with api.context(increment_nest_level=False):
      assert False, 'impossible'  # pragma: no cover
  except ValueError as ex:
    assert 'increment_nest_level=False makes no sense' in ex.message


def GenTests(api):
  yield api.test('basic')

