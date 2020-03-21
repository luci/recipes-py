# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import (DropExpectation, StepCommandContains,
  DoesNotRunRE)

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import invocation as invocation_pb2

DEPS = [
  'resultdb',
]


def RunSteps(api):
  inv_bundle = api.resultdb.chromium_derive(
    step_name='rdb chromium-derive',
    swarming_host='chromium-swarm.appspot.com',
    task_ids=['deadbeef'],
    variants_with_unexpected_results=True,
  )
  invocation_ids = inv_bundle.keys()
  api.resultdb.include_invocations(invocation_ids, step_name='rdb include')
  api.resultdb.remove_invocations(invocation_ids, step_name='rdb remove')


def GenTests(api):
  yield (
    api.test('noop') +
    api.resultdb.chromium_derive(step_name='rdb chromium-derive', results={}) +
    api.post_process(
        DoesNotRunRE, 'rdb include', 'rdb remove') +
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
    api.resultdb.chromium_derive(
        step_name='rdb chromium-derive', results=inv_bundle) +
    api.post_process(
        StepCommandContains, 'rdb include', ['-add', 'invid,invid2']) +
    api.post_process(
        StepCommandContains, 'rdb remove', ['-remove', 'invid,invid2']) +
    api.post_process(DropExpectation)
  )
