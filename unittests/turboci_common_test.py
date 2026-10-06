#!/usr/bin/env vpython3
# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from unittest import mock

from google.protobuf import message
from google.protobuf import proto_json
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2

import test_env
import turboci_test_helper

from PB.turboci.graph.ids.v1 import identifier as identifier_pb
from PB.turboci.graph.orchestrator.v1 import check_kind as check_kind_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import edge as edge_pb
from PB.turboci.graph.orchestrator.v1 import query as query_pb
from PB.turboci.graph.orchestrator.v1 import (
    query_nodes_request as query_nodes_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import revision as revision_pb
from PB.turboci.graph.orchestrator.v1 import type_info as type_info_pb
from PB.turboci.graph.orchestrator.v1 import type_set as type_set_pb
from PB.turboci.graph.orchestrator.v1 import value_write as value_write_pb
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_request as write_nodes_request_pb,
)
from turboci.utils import value

from recipe_engine import turboci
from recipe_engine.internal.turboci import common


def _mkStruct(d: Mapping[str, Any]) -> struct_pb2.Struct:
  return cast(struct_pb2.Struct, proto_json.parse(struct_pb2.Struct, d))


def _mkValue(
    msg: message.Message, realm: str | None = None
) -> value_write_pb.ValueWrite:
  ret = value_write_pb.ValueWrite()
  if realm:
    ret.realm = realm
  ret.data.Pack(msg, deterministic=True)
  return ret


class TestCheckID(test_env.RecipeEngineUnitTest):
  def test_ok(self) -> None:
    self.assertEqual(
        turboci.check_id('fleem'), identifier_pb.Check(id='fleem'))
    self.assertEqual(
        turboci.check_id('fleem', in_workplan='123'),
        identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id='123'),
            id='fleem',
        ))
    self.assertEqual(
        turboci.check_id('fleem', in_workplan='L321'),
        identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id='321'),
            id='fleem',
        ))

  def test_fail(self) -> None:
    with self.assertRaisesRegex(ValueError, 'must not contain'):
      turboci.check_id('not:cool')

    with self.assertRaises(ValueError) as ex:
      turboci.check_id('just fine', in_workplan='bad news')
    self.assertRegex(str(ex.exception), 'work_plan: id must be parsable')


class TestReason(test_env.RecipeEngineUnitTest):
  def test_ok(self) -> None:
    r = turboci.reason("some string", _mkStruct({'a': 'b'}))

    self.assertEqual(
        r,
        write_nodes_request_pb.WriteNodesRequest.Reason(
            message="some string",
            details=[_mkValue(_mkStruct({'a': 'b'}))],
        ))


class TestDepGroup(test_env.RecipeEngineUnitTest):
  def test_ok(self) -> None:
    dg = turboci.dep_group(
        'stuff',
        identifier_pb.Identifier(check=identifier_pb.Check(id="things")),
        identifier_pb.Check(id="more"),
        turboci.dep_group('nested-1', 'nested-2', in_workplan='L123456'),
        threshold=3,
    )
    self.assertEqual(
        dg,
        write_nodes_request_pb.WriteNodesRequest.DependencyGroup(
            edges=[
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('stuff'))),
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('things'))),
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('more'))),
            ],
            groups=[
                write_nodes_request_pb.WriteNodesRequest.DependencyGroup(
                    edges=[
                        edge_pb.Edge(
                            check=edge_pb.Edge.Check(
                                identifier=turboci.check_id(
                                    'nested-1', in_workplan='123456'))),
                        edge_pb.Edge(
                            check=edge_pb.Edge.Check(
                                identifier=turboci.check_id(
                                    'nested-2', in_workplan='123456'))),
                    ]),
            ],
            threshold=3,
        ))


class TestCheck(test_env.RecipeEngineUnitTest):
  def test_ok(self) -> None:
    chk = turboci.check(
        'the check id',
        kind='CHECK_KIND_TEST',
        state='CHECK_STATE_PLANNED',
        options=[_mkStruct({'a': 'b'})],
        deps=turboci.dep_group(
            "stuff",
            "things",
        ),
        results=[_mkStruct({'cool': ['result']})],
        finalize_results=True,
        in_workplan='321',
        realm='project/check/realm',
        realm_options=[
            ('project/check/option/realm',
             struct_pb2.Value(string_value='realm_option')),
        ],
        realm_results=[
            ('project/check/result/realm',
             struct_pb2.Value(string_value='realm_result')),
        ],
    )

    self.assertEqual(
        chk,
        write_nodes_request_pb.WriteNodesRequest.CheckWrite(
            identifier=identifier_pb.Check(
                work_plan=identifier_pb.WorkPlan(id='321'),
                id='the check id',
            ),
            realm='project/check/realm',
            kind=check_kind_pb.CheckKind.CHECK_KIND_TEST,
            options=[
                _mkValue(_mkStruct({'a': 'b'})),
                _mkValue(
                    struct_pb2.Value(string_value='realm_option'),
                    realm='project/check/option/realm'),
            ],
            dependencies=(
                write_nodes_request_pb.WriteNodesRequest.DependencyGroup(
                    edges=[
                        edge_pb.Edge(
                            check=edge_pb.Edge.Check(
                                identifier=turboci.check_id('stuff'))),
                        edge_pb.Edge(
                            check=edge_pb.Edge.Check(
                                identifier=turboci.check_id('things'))),
                    ],
                )
            ),
            result_data=[
                _mkValue(_mkStruct({'cool': ['result']})),
                _mkValue(
                    struct_pb2.Value(string_value='realm_result'),
                    realm='project/check/result/realm'),
            ],
            finalize_results=True,
            state=check_state_pb.CheckState.CHECK_STATE_PLANNED,
        ))


class TestWriteNodes(test_env.RecipeEngineUnitTest):

  def setUp(self) -> None:
    self.m = mock.MagicMock()
    common.CLIENT = self.m
    return super().setUp()

  def tearDown(self) -> None:
    common.CLIENT = None
    return super().tearDown()

  def test_write_nodes(self) -> None:
    # User writes:
    turboci.write_nodes(
        turboci.check(
            "someid",
            kind='CHECK_KIND_BUILD',
            options=[
                _mkStruct({"cool_opt": [1, 2, 3]}),
            ]),
        turboci.reason("I feel like it", _mkStruct({"hello": "world"})),
    )

    # Raw API call to common.CLIENT.
    self.m.WriteNodes.assert_called_once_with(
        write_nodes_request_pb.WriteNodesRequest(
            reason=write_nodes_request_pb.WriteNodesRequest.Reason(
                message="I feel like it",
                details=[_mkValue(_mkStruct({'hello': 'world'}))],
            ),
            checks=[
                write_nodes_request_pb.WriteNodesRequest.CheckWrite(
                    identifier=identifier_pb.Check(id="someid"),
                    kind=check_kind_pb.CheckKind.CHECK_KIND_BUILD,
                    options=[_mkValue(_mkStruct({'cool_opt': [1, 2, 3]}))],
                ),
            ],
        ))

  def test_query_nodes(self) -> None:
    turboci.query_nodes(
        turboci.make_query(
            node_set=[turboci.check_id("bob")],
        ),
        turboci.make_query(
            query_pb.Query.SelectChecks.Predicate(kind='CHECK_KIND_TEST'),
            query_pb.Query.CollectChecks(options=True),
        ),
        version=query_nodes_request_pb.QueryNodesRequest.VersionRestriction(
            require=revision_pb.Revision(
                ts=timestamp_pb2.Timestamp(seconds=1234, nanos=5678)),
        ))

    self.m.QueryNodes.assert_called_once_with(
        query_nodes_request_pb.QueryNodesRequest(
            type_info=type_info_pb.TypeInfo(wanted=type_set_pb.TypeSet()),
            query=[
                query_pb.Query(
                    nodes_by_id=query_pb.Query.NodesByID(nodes=[
                        identifier_pb.Identifier(
                            check=identifier_pb.Check(id="bob"))
                    ]),),
                query_pb.Query(
                    nodes_in_workplan=identifier_pb.WorkPlan(),
                    select_checks=query_pb.Query.SelectChecks(predicates=[
                        query_pb.Query.SelectChecks.Predicate(
                            kind='CHECK_KIND_TEST'),
                    ]),
                    collect_checks=query_pb.Query.CollectChecks(options=True,),
                ),
            ],
            version=query_nodes_request_pb.QueryNodesRequest.VersionRestriction(
                require=revision_pb.Revision(
                    ts=timestamp_pb2.Timestamp(seconds=1234, nanos=5678)),),
        ))


if __name__ == '__main__':
  test_env.main()
