#!/usr/bin/env vpython3
# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from unittest import mock

import test_env

from PB.turboci.graph.ids.v1.identifier import Check, Stage, WorkPlan
from PB.turboci.graph.ids.v1 import identifier_kind
from PB.turboci.graph.orchestrator.v1 import check_kind as check_kind_pb2
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb2
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import (
    QueryNodesRequest,)
from PB.turboci.graph.orchestrator.v1.read_workplan_request import (
    ReadWorkPlanRequest,)
from PB.turboci.graph.orchestrator.v1.read_workplan_response import (
    ReadWorkPlanResponse,)
from PB.turboci.graph.orchestrator.v1.value_data import ValueData
from PB.turboci.graph.orchestrator.v1.type_set import TypeSet
from PB.turboci.graph.orchestrator.v1.write_nodes_request import (
    WriteNodesRequest,)
from PB.turboci.graph.orchestrator.v1.write_nodes_response import (
    WriteNodesResponse,)

from recipe_engine.internal.turboci.grpc_client import TurboCIGRPCClient
from turboci.utils import ids
from turboci.utils.client import errors


class TurboCIGRPCClientTest(test_env.RecipeEngineUnitTest):

  def setUp(self):
    super().setUp()
    self.client = TurboCIGRPCClient('localhost:12345', wpid=WorkPlan(id='123'))
    self.mock_read_work_plan = mock.patch.object(
        self.client.transport, '_read_work_plan', autospec=True).start()
    self.mock_read_work_plan.return_value = ReadWorkPlanResponse()
    self.addCleanup(mock.patch.stopall)

  def test_query_nodes_select_checks_by_id(self):
    """Tests that QueryNodes can select checks by their ID over gRPC client."""
    mock_response = ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check1'))
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check2'))
    self.mock_read_work_plan.return_value = mock_response

    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        check=Check(work_plan=WorkPlan(id="123"), id='check1'))

    response = self.client.QueryNodes(req)

    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 1)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'check1')

  def test_write_nodes_delegates_to_transport(self):
    """Tests that WriteNodes cleanly delegates to the underlying transport."""
    req = WriteNodesRequest()
    mock_resp = WriteNodesResponse()
    with mock.patch.object(
        self.client.transport, 'call_unary',
        return_value=mock_resp) as mock_call:
      res = self.client.WriteNodes(req)
      self.assertEqual(res, mock_resp)
      mock_call.assert_called_once()
      self.assertEqual(mock_call.call_args[0][0], 'WriteNodes')

  def test_wpid_parsing(self):
    """Tests that TurboCIGRPCClient correctly accepts and binds an
    `identifier.WorkPlan` object on construction."""
    wp_proto, _, _ = ids.root(ids.from_string('L12345:S67:A1'))
    self.assertIsNotNone(wp_proto)
    self.assertEqual(wp_proto.id, '12345')

    c1 = TurboCIGRPCClient('localhost:12345', wpid=wp_proto)
    self.assertEqual(c1.wpid.id, '12345')

  def test_rpc_retry_logging(self):
    """Tests that transient RPC errors trigger warning logs and retries."""
    req = WriteNodesRequest()
    mock_resp = WriteNodesResponse()
    err = errors.RetryableRPCError.make('Server temporarily unavailable')

    with mock.patch.object(
        self.client.transport, 'call_unary',
        side_effect=[err, mock_resp]) as mock_call:
      with self.assertLogs(level='WARNING') as cm:
        res = self.client.WriteNodes(req)
        self.assertEqual(res, mock_resp)
        self.assertEqual(mock_call.call_count, 2)
        self.assertTrue(
            any('Transient error in RPC WriteNodes' in output
                for output in cm.output))


if __name__ == '__main__':
  test_env.main()
