# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

DEPS = [
  'assertions',
  'buildbucket',
  'context',
  'step',
  'swarming',
]


def RunSteps(api):
  def basic_request():
    request = api.swarming.task_request()
    return request.with_slice(0, request[0].
        with_command(['echo', 'hi']).
        with_dimensions(pool='example.pool', os='Debian'))

  with api.context(realm='some:realm'):
    request = basic_request().with_resultdb()
    api.assertions.assertEqual('some:realm', request.realm)
    request.to_jsonish()  # doesn't blow up

  with api.context(realm=''):
    request = basic_request().with_resultdb()
    api.assertions.assertEqual(None, request.realm)
    res = request.to_jsonish()
    # Picks up builder's realm.
    api.assertions.assertEqual('proj:buck', res['realm'])


def GenTests(api):
  yield (
      api.test('basic') +
      api.buildbucket.ci_build(project='proj', bucket='buck') +
      api.post_process(DropExpectation))
