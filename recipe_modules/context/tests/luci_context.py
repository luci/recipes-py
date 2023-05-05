# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2

DEPS = [
  'assertions',
  'context',
  'path',
  'step',
]

def RunSteps(api):
  def assert_msg_equal(expected, actual):
    api.assertions.assertEqual(
      expected.SerializeToString(deterministic=True),
      actual.SerializeToString(deterministic=True)
    )

  api.step('start', ['echo', 'hello'])
  assert_msg_equal(sections_pb2.LUCIExe(cache_dir='/path/to/cache'),
                   api.context.luciexe)
  api.assertions.assertEqual(
      'invocations/inv', api.context.resultdb_invocation_name)

  api.assertions.assertEqual('proj:realm', api.context.realm)
  with api.context(env={'UNRELATED_CHANGE': 1}):
    api.assertions.assertEqual('proj:realm', api.context.realm)
  with api.context(realm='proj:another'):
    api.assertions.assertEqual('proj:another', api.context.realm)
  with api.context(realm=''):
    api.assertions.assertEqual(None, api.context.realm)

  with api.context(
    luciexe=sections_pb2.LUCIExe(cache_dir='/path/to/new_cache')):
    api.step('new luciexe', ['echo', 'new', 'luciexe'])
    assert_msg_equal(sections_pb2.LUCIExe(cache_dir='/path/to/new_cache'),
                     api.context.luciexe)

  api.step('end', ['echo', 'bye'])
  assert_msg_equal(sections_pb2.LUCIExe(cache_dir='/path/to/cache'),
                   api.context.luciexe)

def GenTests(api):
  yield (
    api.test('basic')
    + api.context.luci_context(
      luciexe=sections_pb2.LUCIExe(cache_dir='/path/to/cache'),
      realm=sections_pb2.Realm(name='proj:realm'),
      resultdb=sections_pb2.ResultDB(
          current_invocation=sections_pb2.ResultDBInvocation(
              name='invocations/inv',
              update_token='token',
          ),
          hostname='rdbhost',
      )
    )
  )

  assert api.context.realm is None
