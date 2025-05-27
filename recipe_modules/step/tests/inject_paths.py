# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'context',
  'path',
  'step',
  'properties',
]


def RunSteps(api):
  with api.context(env={'FOO': 'bar'}):
    api.step('test step (no env)', ['echo', 'hi'])

  with api.context(env={'PATH': 'something'}):
    api.step('test step (env)', ['echo', 'hi'])

  with api.context(env={
      'PATH': api.path.pathsep.join(('something', '%(PATH)s'))}):
    api.step('test step (env, $PATH)', ['echo', 'hi'])


def GenTests(api):
  yield api.test('basic')
  yield api.test('with_value') + api.properties(**{
    '$recipe_engine/step': {
      'prefix_path': ['foo', 'bar'],
    }
  })

