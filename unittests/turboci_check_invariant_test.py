#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import message
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2

import test_env

from PB.turboci.graph.ids.v1 import identifier as identifier_pb
from PB.turboci.graph.orchestrator.v1 import check as check_pb
from PB.turboci.graph.orchestrator.v1 import check_kind as check_kind_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_request as write_nodes_request_pb,
)
from turboci.utils import ids

from recipe_engine import turboci
from recipe_engine.internal.turboci import check_invariant, edge

demoStruct = struct_pb2.Struct(
    fields={'hello': struct_pb2.Value(string_value='world')})
demoStruct2 = struct_pb2.Struct(
    fields={'hola': struct_pb2.Value(string_value='mundo')})

demoTS = timestamp_pb2.Timestamp(seconds=100, nanos=100)
demoTS2 = timestamp_pb2.Timestamp(seconds=200, nanos=200)


def _mkOptions(
    *msg: type[message.Message] | message.Message,
) -> list[value_ref_pb.ValueRef]:
  ret = []
  for _, m in enumerate(msg):
    vr = value_ref_pb.ValueRef()
    if isinstance(m, type):
      m = m()
    vr.inline.Pack(m, deterministic=True)
    ret.append(vr)
  return ret


class CheckDeltaTest(test_env.RecipeEngineUnitTest):

  def test_PLANNING_maximum(self) -> None:
    delta = turboci.check(
        id='hey',
        kind='CHECK_KIND_ANALYSIS',
        options=[demoStruct],
        deps=turboci.dep_group('other'),
    )
    check_invariant.assert_can_apply(delta, None)

    # can apply same delta to already-created check in PLANNING.
    check_invariant.assert_can_apply(
        delta,
        check_pb.Check(
            identifier=turboci.check_id('hey'),
            kind='CHECK_KIND_ANALYSIS',
            state='CHECK_STATE_PLANNING',
            options=_mkOptions(demoStruct),
            dependencies=edge.extract_dependencies(turboci.dep_group('neat')),
        ))

  def test_creation_errors(self) -> None:
    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          write_nodes_request_pb.WriteNodesRequest.CheckWrite(
              # cannot have : in check_id() - checking error from
              # assert_can_apply
              identifier=identifier_pb.Check(id='hey:there'),
              kind='CHECK_KIND_ANALYSIS',
          ),
          None)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(id='hey',
                        # no kind
                       ),
          None)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              kind='CHECK_KIND_ANALYSIS',
              results=[demoStruct],
              # State is not >= PLANNED
          ),
          None)

    check_invariant.assert_can_apply(
        turboci.check(
            id='hey',
            kind='CHECK_KIND_ANALYSIS',
            results=[demoStruct],
            state=check_state_pb.CheckState.CHECK_STATE_PLANNED,
        ), None)

  def test_PLANNING_errors(self) -> None:
    check = check_pb.Check(
        identifier=ids.check('hey'),
        kind=check_kind_pb.CheckKind.CHECK_KIND_ANALYSIS,
        state=check_state_pb.CheckState.CHECK_STATE_PLANNING,
        options=_mkOptions(demoStruct),
        dependencies=edge.extract_dependencies(turboci.dep_group('neat')),
    )

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # adding results with unresolved dependencies
              results=[demoStruct],
          ),
          check)

    # Note that if we remove the dependencies and advance the state through
    # WAITING, we can write results.
    check_invariant.assert_can_apply(
        turboci.check(
            id='hey',
            deps=turboci.dep_group(),
            state='CHECK_STATE_FINAL',
            results=[demoStruct],
        ), check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # changing kind
              kind=check_kind_pb.CheckKind.CHECK_KIND_BUILD,
          ),
          check)

  def test_PLANNED_errors(self) -> None:
    check = check_pb.Check(
        identifier=ids.check('hey'),
        kind='CHECK_KIND_ANALYSIS',
        state='CHECK_STATE_PLANNED',
        options=_mkOptions(demoStruct),
        dependencies=edge.extract_dependencies(turboci.dep_group('neat')),
    )

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # changing options
              options=[demoStruct2],
          ),
          check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # changing results
              results=[demoStruct2],
          ),
          check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # changing state to WAITING with unresolved dependencies
              state='CHECK_STATE_WAITING',
          ),
          check)


if __name__ == '__main__':
  test_env.main()
