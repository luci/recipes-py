# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import (DropExpectation,
  DoesNotRunRE)

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2

DEPS = [
  'context',
  'resultdb',
]


def RunSteps(api):
  inv_bundle = api.resultdb.query(
    ['deadbeef'],
    step_name='rdb query',
    variants_with_unexpected_results=True,
  )
  invocation_ids = inv_bundle.keys()
  api.resultdb.include_invocations(invocation_ids, step_name='rdb include')
  api.resultdb.exclude_invocations(invocation_ids, step_name='rdb exclude')


def GenTests(api):
  rdb_luci_context = sections_pb2.ResultDB(
      current_invocation=sections_pb2.ResultDBInvocation(
          name='invocations/build:8945511751514863184',
          update_token='token',
      ),
      hostname='rdbhost',
  )
  yield (
    api.test('noop') +
    api.context.luci_context(
        realm=sections_pb2.Realm(name='chromium:ci'),
        resultdb=rdb_luci_context,
    ) +
    api.resultdb.query({}, step_name='rdb query') +
    api.post_process(
        DoesNotRunRE, 'rdb include', 'rdb exclude') +
    api.post_process(DropExpectation)
  )
  inv_bundle = {
      'invid': api.resultdb.Invocation(
          proto=invocation_pb2.Invocation(
              state=invocation_pb2.Invocation.FINALIZED),
      ),
      'invid2': api.resultdb.Invocation(
          proto=invocation_pb2.Invocation(
              state=invocation_pb2.Invocation.FINALIZED),
      ),
  }

  yield (
    api.test('basic') +
    api.context.luci_context(
        realm=sections_pb2.Realm(name='chromium:ci'),
        resultdb=rdb_luci_context,
    ) +
    api.resultdb.query(
        inv_bundle,
        step_name='rdb query')
  )
