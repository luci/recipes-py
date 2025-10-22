#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf.message import Message

import test_env

from google.protobuf.struct_pb2 import Struct, Value
from google.protobuf.timestamp_pb2 import Timestamp

from recipe_engine import turboci
from recipe_engine.internal.turboci import check_invariant
from recipe_engine.internal.turboci.common import check_id

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest

demoStruct = Struct(fields={'hello': Value(string_value='world')})
demoStruct2 = Struct(fields={'hola': Value(string_value='mundo')})

demoTS = Timestamp(seconds=100, nanos=100)
demoTS2 = Timestamp(seconds=200, nanos=200)


def _mkOptions(id: str,
               *msg: type[Message] | Message,
               in_workplan: str = "") -> list[Check.OptionRef]:
  ident = check_id(id, in_workplan=in_workplan)
  return [
      Check.OptionRef(
          type_url=turboci.type_url_for(m),
          identifier=identifier.CheckOption(check=ident, idx=i + 1))
      for i, m in enumerate(msg)
  ]


class CheckDeltaTest(test_env.RecipeEngineUnitTest):

  def test_PLANNING_maximum(self):
    delta = turboci.check(
        id='hey',
        kind='CHECK_KIND_ANALYSIS',
        options=[demoStruct],
        deps=[turboci.edge_group('other')],
    )
    check_invariant.assert_can_apply(delta, None)

    # can apply same delta to already-created check in PLANNING.
    check_invariant.assert_can_apply(
        delta,
        Check(
            identifier=turboci.check_id('hey'),
            kind='CHECK_KIND_ANALYSIS',
            state='CHECK_STATE_PLANNING',
            options=_mkOptions('hey', demoStruct),
            dependencies=[turboci.edge_group('neat')],
        ))

  def test_creation_errors(self):
    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          WriteNodesRequest.CheckWrite(
              # cannot have : in check_id() - checking error from assert_can_apply
              identifier=identifier.Check(id='hey:there'),
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
            state=CheckState.CHECK_STATE_PLANNED,
        ), None)

  def test_PLANNING_errors(self):
    check = Check(
        identifier=check_id('hey'),
        kind=CheckKind.CHECK_KIND_ANALYSIS,
        state=CheckState.CHECK_STATE_PLANNING,
        options=_mkOptions('hey', demoStruct),
        dependencies=[turboci.edge_group('neat')],
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
            deps=[turboci.edge_group()],
            state='CHECK_STATE_FINAL',
            results=[demoStruct],
        ), check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # changing kind
              kind=CheckKind.CHECK_KIND_BUILD,
          ),
          check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      dg = turboci.edge_group("stuff")
      dg.edges[0].resolution.satisfied = True
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # setting dependency groups which are resolved
              deps=[dg],
          ),
          check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      dg = turboci.edge_group("stuff")
      dg.SetInParent
      dg.edges[0].resolution.satisfied = True
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # setting dependency edges which are resolved
              deps=[dg],
          ),
          check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      dg = turboci.edge_group("stuff")
      dg.threshold = -1
      dg.edges[0].resolution.satisfied = True
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # threshold negative
              deps=[dg],
          ),
          check)

    with self.assertRaises(turboci.CheckWriteInvariantException):
      dg = turboci.edge_group("stuff", threshold=10)
      dg.edges[0].resolution.satisfied = True
      check_invariant.assert_can_apply(
          turboci.check(
              id='hey',
              # threshold larger than the group
              deps=[dg],
          ),
          check)

  def test_PLANNED_errors(self):
    check = Check(
        identifier=check_id('hey'),
        kind='CHECK_KIND_ANALYSIS',
        state='CHECK_STATE_PLANNED',
        options=_mkOptions('hey', demoStruct),
        dependencies=[turboci.edge_group('neat')],
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
