#!/usr/bin/env vpython3
# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from unittest import mock

import test_env

from PB.turboci.graph.ids.v1 import identifier as identifier_pb
from PB.turboci.graph.ids.v1 import identifier_kind as identifier_kind_pb
from PB.turboci.graph.orchestrator.v1 import check_kind as check_kind_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import query as query_pb
from PB.turboci.graph.orchestrator.v1 import (
    query_nodes_request as query_nodes_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    read_workplan_request as read_workplan_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    read_workplan_response as read_workplan_response_pb,
)
from PB.turboci.graph.orchestrator.v1 import type_set as type_set_pb
from PB.turboci.graph.orchestrator.v1 import value_data as value_data_pb

from recipe_engine.internal.turboci import turboci as turboci_module


class TurboCIClientTest(test_env.RecipeEngineUnitTest):

  def setUp(self) -> None:
    super().setUp()
    self.client = turboci_module.TurboCIOrchestrator('fake-endpoint')
    self.mock_read_work_plan = mock.patch.object(
        self.client, '_read_work_plan', autospec=True).start()
    self.mock_read_work_plan.return_value = (
        read_workplan_response_pb.ReadWorkPlanResponse()
    )
    self.addCleanup(mock.patch.stopall)

  def test_query_nodes_select_checks_by_id(self) -> None:
    """Tests that QueryNodes can select checks by their ID."""
    # Mock the response from _read_work_plan
    mock_response = read_workplan_response_pb.ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check1'))
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check2'))
    self.mock_read_work_plan.return_value = mock_response

    # Formulate a request to query for a specific check
    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        check=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check1'))

    # Call QueryNodes
    response = self.client.QueryNodes(req)

    # Assert the response contains only the queried check
    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 1)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'check1')

  def test_query_nodes_select_checks_by_kind_and_state(self) -> None:
    """Tests that QueryNodes can filter checks by kind and state."""
    # Mock the response from _read_work_plan
    mock_response = read_workplan_response_pb.ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check1'),
        kind=check_kind_pb.CHECK_KIND_BUILD,
        state=check_state_pb.CHECK_STATE_PLANNED)
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check2'),
        kind=check_kind_pb.CHECK_KIND_TEST,
        state=check_state_pb.CHECK_STATE_PLANNED)
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check3'),
        kind=check_kind_pb.CHECK_KIND_BUILD,
        state=check_state_pb.CHECK_STATE_WAITING)
    self.mock_read_work_plan.return_value = mock_response

    # Formulate a request to query for BUILD checks in PLANNED state
    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_in_workplan.id = "wp_id"
    select_checks = query.select_checks
    predicate = select_checks.predicates.add()
    predicate.kind = check_kind_pb.CHECK_KIND_BUILD
    predicate.state = check_state_pb.CHECK_STATE_PLANNED
    query.collect_checks.CopyFrom(query_pb.Query.CollectChecks())

    # Call QueryNodes
    response = self.client.QueryNodes(req)

    # Assert the response contains only the matching check
    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 1)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'check1')

  def test_query_nodes_no_matching_checks(self) -> None:
    """Tests that QueryNodes returns an empty list when no checks match."""
    # Mock the response from _read_work_plan
    mock_response = read_workplan_response_pb.ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check1'),
        kind=check_kind_pb.CHECK_KIND_BUILD)
    self.mock_read_work_plan.return_value = mock_response

    # Formulate a request to query for a TEST check
    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_in_workplan.id = "wp_id"
    query.select_checks.predicates.add(kind=check_kind_pb.CHECK_KIND_TEST)

    # Call QueryNodes
    response = self.client.QueryNodes(req)

    # Assert the response contains no checks
    self.assertEqual(len(response.workplans), 1)
    self.assertEqual(len(response.workplans[0].checks), 0)

  def test_query_nodes_multiple_queries(self) -> None:
    """Tests that QueryNodes can handle multiple queries."""
    mock_response = read_workplan_response_pb.ReadWorkPlanResponse()
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id="c1"),)
    mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id="c2"),)
    self.mock_read_work_plan.return_value = mock_response

    req = query_nodes_request_pb.QueryNodesRequest()
    req.query.add().nodes_by_id.nodes.add(
        check=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='c1'))
    req.query.add().nodes_by_id.nodes.add(
        check=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='c2'))

    response = self.client.QueryNodes(req)

    self.assertEqual(len(response.workplans[0].checks), 2)
    self.assertEqual(response.workplans[0].checks[0].identifier.id, 'c1')
    self.assertEqual(response.workplans[0].checks[1].identifier.id, 'c2')

  def test_query_to_read_work_plan_request_infers_args(self) -> None:
    """Tests that _query_to_read_work_plan_request infers arguments correctly."""
    req = query_nodes_request_pb.QueryNodesRequest()

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
      mock_read_work_plan.return_value = (
          read_workplan_response_pb.ReadWorkPlanResponse()
      )
      self.client.QueryNodes(req)

    mock_read_work_plan.assert_called_once()
    read_req = mock_read_work_plan.call_args[0][0]
    self.assertIsInstance(
        read_req, read_workplan_request_pb.ReadWorkPlanRequest)
    self.assertEqual(read_req.workplan_id.id, "wp_id")
    self.assertTrue(read_req.value_filter.check_options)
    self.assertTrue(read_req.value_filter.check_result_data)
    self.assertCountEqual(read_req.included_node_types, [
        identifier_kind_pb.IDENTIFIER_KIND_CHECK,
    ])

  def test_query_to_read_work_plan_request_without_workplan_id(self) -> None:
    req = query_nodes_request_pb.QueryNodesRequest()

    query1 = req.query.add()
    query1.nodes_in_workplan.id = ""
    query1.collect_checks.options = True

    with mock.patch.object(self.client,
                           '_read_work_plan') as mock_read_work_plan:
      # _read_work_plan should return a ReadWorkPlanResponse
      mock_read_work_plan.return_value = (
          read_workplan_response_pb.ReadWorkPlanResponse()
      )
      self.client.QueryNodes(req)

    mock_read_work_plan.assert_called_once()
    read_req = mock_read_work_plan.call_args[0][0]
    self.assertIsInstance(
        read_req, read_workplan_request_pb.ReadWorkPlanRequest)
    self.assertFalse(read_req.HasField('workplan_id'))

  def test_query_to_read_work_plan_request_with_different_workplan_id(
      self,
  ) -> None:
    req = query_nodes_request_pb.QueryNodesRequest()

    # Query 1: wants checks with options
    query1 = req.query.add()
    query1.nodes_in_workplan.id = "wp_id"
    query1.collect_checks.options = True

    # Query 2: wants checks with results
    query2 = req.query.add()
    query2.nodes_in_workplan.id = "wp2_id"
    query1.collect_checks.result_data = True
    with self.assertRaisesRegex(NotImplementedError, 'multiple workplans'):
      self.client.QueryNodes(req)

  def test_query_to_read_work_plan_request_with_and_without_workplan_id(
      self,
  ) -> None:
    req = query_nodes_request_pb.QueryNodesRequest()

    # Query 1: wants checks with options
    query1 = req.query.add()
    query1.nodes_in_workplan.id = "wp_id"
    query1.collect_checks.options = True

    # Query 2: wants checks with results
    query2 = req.query.add()
    query2.nodes_in_workplan.id = ""
    query1.collect_checks.result_data = True
    with self.assertRaisesRegex(NotImplementedError, 'multiple workplans'):
      self.client.QueryNodes(req)

  def test_filter_read_work_plan_responses_with_option_type(self) -> None:
    """Tests filtering checks and stages by various attributes."""
    mock_response = read_workplan_response_pb.ReadWorkPlanResponse()
    check1 = mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check1'))
    check1.options.add(
        type_url='type.googleapis.com/my.OptionA', digest='digest1')
    check2 = mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check2'))
    check2.options.add(type_url='type.googleapis.com/my.OptionB')
    check3 = mock_response.workplan.checks.add(
        identifier=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="123"), id='check3'))
    check3.options.add(type_url='type.googleapis.com/my.OptionA')
    check3.options.add(type_url='type.googleapis.com/my.OptionB')

    mock_response.value_data['digest1'].CopyFrom(
        value_data_pb.ValueData(
            json=value_data_pb.ValueData.JsonAny(value='some-data')))

    self.mock_read_work_plan.return_value = mock_response

    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_in_workplan.id = "wp_id"
    # Select checks with option type A
    query.select_checks.predicates.add(
        with_option_type=type_set_pb.TypeSet(
            type_urls=['type.googleapis.com/my.OptionA']))
    query.collect_checks.CopyFrom(query_pb.Query.CollectChecks(options=True))

    response = self.client.QueryNodes(req)

    self.assertEqual(len(response.workplans[0].checks), 2)
    ret_check = response.workplans[0].checks[0]
    self.assertEqual(ret_check.identifier.id, 'check1')
    self.assertEqual(ret_check.options[0].type_url,
                     'type.googleapis.com/my.OptionA')
    self.assertEqual(response.workplans[0].checks[1].identifier.id, 'check3')
    self.assertEqual(response.value_data['digest1'].json.value, 'some-data')

  def test_query_nodes_multiple_workplans_not_supported(self) -> None:
    """Tests that querying multiple workplans raises NotImplementedError."""
    req = query_nodes_request_pb.QueryNodesRequest()
    wp1_id = identifier_pb.WorkPlan(id='wp1')
    wp2_id = identifier_pb.WorkPlan(id='wp2')

    query1 = req.query.add()
    query1.nodes_in_workplan.CopyFrom(wp1_id)

    query2 = req.query.add()
    query2.nodes_in_workplan.CopyFrom(wp2_id)

    with self.assertRaises(NotImplementedError):
      self.client.QueryNodes(req)

  def test_query_nodes_unsupported_node_set(self) -> None:
    """Tests that QueryNodes raises for unsupported node_set types."""
    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_across_workplans.CopyFrom(
        query_pb.Query.NodesAcrossWorkPlans())
    with self.assertRaisesRegex(NotImplementedError, 'nodes_across_workplans'):
      self.client.QueryNodes(req)

  def test_query_nodes_for_edits(self) -> None:
    """Tests that QueryNodes raises for edits."""
    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        check=identifier_pb.Check(
            work_plan=identifier_pb.WorkPlan(id="wp_id"), id='check1'))
    query.collect_checks.edits.SetInParent()
    with self.assertRaisesRegex(NotImplementedError, 'edits'):
      self.client.QueryNodes(req)

  def test_query_nodes_for_stages(self) -> None:
    """Tests that QueryNodes raises for stages."""
    req = query_nodes_request_pb.QueryNodesRequest()
    query = req.query.add()
    query.nodes_by_id.nodes.add(
        stage=identifier_pb.Stage(
            work_plan=identifier_pb.WorkPlan(id="wp_id"), id='stage1'))
    with self.assertRaisesRegex(NotImplementedError, 'stages'):
      self.client.QueryNodes(req)


if __name__ == '__main__':
  test_env.main()
