#!/usr/bin/env vpython3
# Copyright 2026 The LUCI Authors. All rights reserved.
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
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.read_workplan_request import ReadWorkPlanRequest
from PB.turboci.graph.orchestrator.v1.read_workplan_response import ReadWorkPlanResponse
from PB.turboci.graph.orchestrator.v1.value_data import ValueData
from PB.turboci.graph.orchestrator.v1.type_set import TypeSet

from recipe_engine.internal.turboci.turboci import TurboCIOrchestrator


class TurboCIClientTest(test_env.RecipeEngineUnitTest):

  def setUp(self):
    super().setUp()
    self.client = TurboCIOrchestrator('fake-endpoint')
    self.mock_read_work_plan = mock.patch.object(
        self.client, '_read_work_plan', autospec=True).start()
    self.mock_read_work_plan.return_value = ReadWorkPlanResponse()
    self.addCleanup(mock.patch.stopall)

  def test_query_nodes_select_checks_by_id(self):
    """Tests that QueryNodes can select checks by their ID."""
    # Mock the response from _read_work_plan
    mock_response = ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check1'))
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check2'))
    self.mock_read_work_plan.return_value = mock_response

    # Formulate a request to query for a specific check
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        check=Check(work_plan=WorkPlan(id="123"), id='check1'))

    # Call QueryNodes
    response = self.client.QueryNodes(req)

    # Assert the response contains only the queried check
    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 1)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'check1')

  def test_query_nodes_select_checks_by_kind_and_state(self):
    """Tests that QueryNodes can filter checks by kind and state."""
    # Mock the response from _read_work_plan
    mock_response = ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check1'),
        kind=check_kind_pb2.CHECK_KIND_BUILD,
        state=check_state_pb2.CHECK_STATE_PLANNED)
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check2'),
        kind=check_kind_pb2.CHECK_KIND_TEST,
        state=check_state_pb2.CHECK_STATE_PLANNED)
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check3'),
        kind=check_kind_pb2.CHECK_KIND_BUILD,
        state=check_state_pb2.CHECK_STATE_WAITING)
    self.mock_read_work_plan.return_value = mock_response

    # Formulate a request to query for BUILD checks in PLANNED state
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_in_workplan.id = "wp_id"
    select_checks = query.select_checks
    predicate = select_checks.predicates.add()
    predicate.kind = check_kind_pb2.CHECK_KIND_BUILD
    predicate.state = check_state_pb2.CHECK_STATE_PLANNED
    query.collect_checks.CopyFrom(Query.CollectChecks())

    # Call QueryNodes
    response = self.client.QueryNodes(req)

    # Assert the response contains only the matching check
    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 1)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'check1')

  def test_query_nodes_no_matching_checks(self):
    """Tests that QueryNodes returns an empty list when no checks match."""
    # Mock the response from _read_work_plan
    mock_response = ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check1'),
        kind=check_kind_pb2.CHECK_KIND_BUILD)
    self.mock_read_work_plan.return_value = mock_response

    # Formulate a request to query for a TEST check
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_in_workplan.id = "wp_id"
    query.select_checks.predicates.add(kind=check_kind_pb2.CHECK_KIND_TEST)

    # Call QueryNodes
    response = self.client.QueryNodes(req)

    # Assert the response contains no checks
    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 0)

  def test_query_nodes_multiple_queries(self):
    """Tests that QueryNodes can handle multiple queries."""
    mock_response = ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id="c1"),)
    mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id="c2"),)
    self.mock_read_work_plan.return_value = mock_response

    req = QueryNodesRequest()
    req.query.add().nodes_by_id.nodes.add(
        check=Check(work_plan=WorkPlan(id="123"), id='c1'))
    req.query.add().nodes_by_id.nodes.add(
        check=Check(work_plan=WorkPlan(id="123"), id='c2'))

    response = self.client.QueryNodes(req)

    self.assertEqual(len(response.workplans[0].checks), 2)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'c1')
    self.assertEqual(response.workplans[0].checks[1].identifier.id, 'c2')

  def test_query_to_read_work_plan_request_infers_args(self):
    """Tests that _query_to_read_work_plan_request infers arguments correctly."""
    req = QueryNodesRequest()

    # Query 1: wants checks with options
    query1 = req.query.add()
    query1.nodes_in_workplan.id = "wp_id"
    query1.collect_checks.options = True

    # Query 2: wants checks with results
    query2 = req.query.add()
    query2.nodes_in_workplan.id = "wp_id"
    query1.collect_checks.result_data = True

    with mock.patch.object(self.client,
                           '_read_work_plan') as mock_read_work_plan:
      # _read_work_plan should return a ReadWorkPlanResponse
      mock_read_work_plan.return_value = ReadWorkPlanResponse()
      self.client.QueryNodes(req)

    mock_read_work_plan.assert_called_once()
    read_req = mock_read_work_plan.call_args[0][0]
    self.assertIsInstance(read_req, ReadWorkPlanRequest)
    self.assertEqual(read_req.workplan_id.id, "wp_id")
    self.assertTrue(read_req.value_filter.check_options)
    self.assertTrue(read_req.value_filter.check_result_data)
    self.assertCountEqual(read_req.included_node_types, [
        identifier_kind.IDENTIFIER_KIND_CHECK,
    ])

  def test_filter_read_work_plan_responses_with_option_type(self):
    """Tests filtering checks and stages by various attributes."""
    mock_response = ReadWorkPlanResponse()
    check1 = mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check1'))
    check1.options.add(
        type_url='type.googleapis.com/my.OptionA', digest='digest1')
    check2 = mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check2'))
    check2.options.add(type_url='type.googleapis.com/my.OptionB')
    check3 = mock_response.workplan.checks.add(
        identifier=Check(work_plan=WorkPlan(id="123"), id='check3'))
    check3.options.add(type_url='type.googleapis.com/my.OptionA')
    check3.options.add(type_url='type.googleapis.com/my.OptionB')

    mock_response.value_data['digest1'].CopyFrom(
        ValueData(json=ValueData.JsonAny(value='some-data')))

    self.mock_read_work_plan.return_value = mock_response

    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_in_workplan.id = "wp_id"
    # Select checks with option type A
    query.select_checks.predicates.add(
        with_option_type=TypeSet(type_urls=['type.googleapis.com/my.OptionA']))
    query.collect_checks.CopyFrom(Query.CollectChecks(options=True))

    response = self.client.QueryNodes(req)

    self.assertEqual(len(response.workplans[0].checks), 2)
    ret_check = response.workplans[0].checks[0]
    self.assertEqual(ret_check.identifier.id, 'check1')
    self.assertEqual(ret_check.options[0].type_url,
                     'type.googleapis.com/my.OptionA')
    self.assertEqual(response.workplans[0].checks[1].identifier.id, 'check3')
    self.assertEqual(response.value_data['digest1'].json.value, 'some-data')

  def test_query_nodes_multiple_workplans_not_supported(self):
    """Tests that querying multiple workplans raises NotImplementedError."""
    req = QueryNodesRequest()
    wp1_id = WorkPlan(id='wp1')
    wp2_id = WorkPlan(id='wp2')

    query1 = req.query.add()
    query1.nodes_in_workplan.CopyFrom(wp1_id)

    query2 = req.query.add()
    query2.nodes_in_workplan.CopyFrom(wp2_id)

    with self.assertRaises(NotImplementedError):
      self.client.QueryNodes(req)

  def test_query_nodes_unsupported_node_set(self):
    """Tests that QueryNodes raises for unsupported node_set types."""
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_across_workplans.CopyFrom(Query.NodesAcrossWorkPlans())
    with self.assertRaisesRegex(NotImplementedError, 'nodes_across_workplans'):
      self.client.QueryNodes(req)

  def test_query_nodes_no_workplan_id(self):
    """Tests that QueryNodes raises when no workplan ID can be found."""
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(check=Check(id='check1'))
    with self.assertRaisesRegex(ValueError, 'Failed to extract workplan id'):
      self.client.QueryNodes(req)

  def test_query_nodes_for_edits(self):
    """Tests that QueryNodes raises for edits."""
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        check=Check(work_plan=WorkPlan(id="wp_id"), id='check1'))
    query.collect_checks.edits.SetInParent()
    with self.assertRaisesRegex(NotImplementedError, 'edits'):
      self.client.QueryNodes(req)

  def test_query_nodes_for_stages(self):
    """Tests that QueryNodes raises for stages."""
    req = QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        stage=Stage(work_plan=WorkPlan(id="wp_id"), id='stage1'))
    with self.assertRaisesRegex(NotImplementedError, 'stages'):
      self.client.QueryNodes(req)


if __name__ == '__main__':
  test_env.main()
