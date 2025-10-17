#!/usr/bin/env vpython3
# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from typing import cast

from unittest.mock import MagicMock

from google.protobuf.timestamp_pb2 import Timestamp

import test_env

from google.protobuf.message import Message

from recipe_engine.internal.turboci.ids import wrap_id

from google.protobuf.any_pb2 import Any
from google.protobuf.struct_pb2 import Struct, Value
from google.protobuf.proto_json import parse

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.edge_group import EdgeGroup
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest

from recipe_engine.internal.turboci import common
from recipe_engine.turboci import (
  write_nodes, reason, check, edge_group, check_id, query_nodes, make_query)


def _mkStruct(d: dict) -> Struct:
  return cast(Struct, parse(Struct, d))


def _mkAny(msg: Message) -> Any:
  ret = Any()
  ret.Pack(msg, deterministic=True)
  return ret


class TestCheckID(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    self.assertEqual(check_id('fleem'), identifier.Check(id='fleem'))
    self.assertEqual(check_id('fleem', in_workplan='123'), identifier.Check(
        work_plan=identifier.WorkPlan(id='123'),
        id='fleem',
    ))
    self.assertEqual(check_id('fleem', in_workplan='L321'), identifier.Check(
        work_plan=identifier.WorkPlan(id='321'),
        id='fleem',
    ))

  def test_fail(self):
    with self.assertRaisesRegex(ValueError, 'must not contain'):
      check_id('not:cool')

    with self.assertRaises(ValueError) as ex:
      check_id('just fine', in_workplan='bad news')
    self.assertRegex(ex.exception.__notes__[0], 'in_workplan: id must be parsable')


class TestReason(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    r = reason("some string", _mkStruct({'a': 'b'}), realm='project/realm')

    self.assertEqual(r, WriteNodesRequest.Reason(
        reason="some string",
        realm="project/realm",
        details=[_mkAny(_mkStruct({'a': 'b'}))],
    ))


class TestDepGroup(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    eg = edge_group(
        'stuff',
        identifier.Identifier(check=identifier.Check(id="things")),
        identifier.Check(id="more"),
        edge_group('nested-1', 'nested-2', in_workplan='L123456'),
        threshold=3,
    )
    self.assertEqual(eg, EdgeGroup(
        edges=[
          Edge(target=identifier.Identifier(check=identifier.Check(id='stuff'))),
          Edge(target=identifier.Identifier(check=identifier.Check(id='things'))),
          Edge(target=identifier.Identifier(check=identifier.Check(id='more'))),
        ],
        groups=[
          EdgeGroup(edges=[
            Edge(target=identifier.Identifier(check=identifier.Check(
                work_plan=identifier.WorkPlan(id="123456"),
                id='nested-1'))),
            Edge(target=identifier.Identifier(check=identifier.Check(
                work_plan=identifier.WorkPlan(id="123456"),
                id='nested-2'))),
          ]),
        ],
        threshold=3,
    ))


class TestCheck(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    chk = check(
        'the check id',
        kind='TEST',
        state='PLANNED',
        options=[_mkStruct({'a': 'b'})],
        deps=[edge_group("stuff", "things",)],
        results=[_mkStruct({'cool': ['result']})],
        finalize_results=True,

        in_workplan='321',
        realm='project/check/realm',
        realm_options=[
          ('project/check/option/realm', Value(string_value='realm_option')),
        ],
        realm_results=[
          ('project/check/result/realm', Value(string_value='realm_result')),
        ],
    )

    self.assertEqual(chk, WriteNodesRequest.CheckWrite(
        identifier=identifier.Check(
            work_plan=identifier.WorkPlan(id='321'),
            id='the check id',
        ),
        realm='project/check/realm',
        kind=CheckKind.CHECK_KIND_TEST,
        options=[
          WriteNodesRequest.RealmValue(
              value=_mkAny(_mkStruct({'a': 'b'})),
          ),
          WriteNodesRequest.RealmValue(
              realm='project/check/option/realm',
              value=_mkAny(Value(string_value='realm_option')),
          ),
        ],
        dependencies=[
          EdgeGroup(
              edges=[
                Edge(target=wrap_id(identifier.Check(id='stuff'))),
                Edge(target=wrap_id(identifier.Check(id='things'))),
              ],
          ),
        ],
        results=[
          WriteNodesRequest.RealmValue(
              value=_mkAny(_mkStruct({'cool': ['result']})),
          ),
          WriteNodesRequest.RealmValue(
              realm='project/check/result/realm',
              value=_mkAny(Value(string_value='realm_result')),
          ),
        ],
        finalize_results=True,
        state=CheckState.CHECK_STATE_PLANNED,
    ))


class TestWriteNodes(test_env.RecipeEngineUnitTest):

  def setUp(self):
    self.m = MagicMock()
    common.CLIENT = self.m
    return super().setUp()

  def tearDown(self):
    common.CLIENT = None
    return super().tearDown()

  def test_write_nodes(self):
    # User writes:
    write_nodes(
        check("someid", kind='BUILD', options=[
          _mkStruct({"cool_opt": [1, 2, 3]}),
        ]),
        reason("I feel like it", _mkStruct({"hello": "world"})),
    )

    # Raw API call to common.CLIENT.
    self.m.WriteNodes.assert_called_once_with(WriteNodesRequest(
        reasons=[WriteNodesRequest.Reason(
            reason="I feel like it",
            details=[_mkAny(_mkStruct({'hello': 'world'}))],
        )],
        checks=[
          WriteNodesRequest.CheckWrite(
              identifier=identifier.Check(id="someid"),
              kind=CheckKind.CHECK_KIND_BUILD,
              options=[
                WriteNodesRequest.RealmValue(
                    value=_mkAny(_mkStruct({'cool_opt': [1, 2, 3]})),
                )
              ],
          ),
        ],
    ))

  def test_query_nodes(self):
    query_nodes(
        make_query(
            Query.Select(nodes=[wrap_id(check_id("bob"))]),
        ), make_query(
            Query.Select.CheckPattern(id_regex='nerp'),
            Query.Collect.Check(options=True),
        ),
        version=QueryNodesRequest.VersionRestriction(
            require=Revision(ts=Timestamp(seconds=1234, nanos=5678)),
        ))

    self.m.QueryNodes.assert_called_once_with(QueryNodesRequest(
        query=[
          Query(select=Query.Select(
              nodes=[identifier.Identifier(check=identifier.Check(id="bob"))],
          )),
          Query(
              select=Query.Select(check_patterns=[
                Query.Select.CheckPattern(id_regex="nerp")
              ]),
              collect=Query.Collect(check=Query.Collect.Check(
                  options=True,
              ))
          ),
        ],
        version=QueryNodesRequest.VersionRestriction(
            require=Revision(ts=Timestamp(seconds=1234, nanos=5678)),
        ),
    ))


if __name__ == '__main__':
  test_env.main()
