# Copyright 2026 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Real client to the TurboCI Orchestrator service."""

import logging
import sys

from gevent import subprocess

from google.protobuf import json_format as jsonpb
from google.protobuf.message import Message

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.ids.v1 import identifier_kind
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.query_nodes_response import QueryNodesResponse
from PB.turboci.graph.orchestrator.v1.read_workplan_request import ReadWorkPlanRequest
from PB.turboci.graph.orchestrator.v1.read_workplan_response import ReadWorkPlanResponse
from PB.turboci.graph.orchestrator.v1.value_mask import VALUE_MASK_VALUE_TYPE
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.orchestrator.v1.write_nodes_response import WriteNodesResponse

from .common import TurboCIClient
from .query_util import type_set_to_re, want_value_ref

LOG = logging.getLogger(__name__)
TURBOCI = 'turboci.exe' if sys.platform == 'win32' else 'turboci'


class TurboCIOrchestrator(TurboCIClient):

  def __init__(self, endpoint: str):
    super().__init__()
    self.endpoint = endpoint

  def WriteNodes(self, req: WriteNodesRequest) -> WriteNodesResponse:
    self._log_request('write-nodes', req)
    ret = self._run_cmd('write-nodes', req.SerializeToString())
    res = WriteNodesResponse()
    res.ParseFromString(ret)
    LOG.info('write-nodes response: %s', jsonpb.MessageToJson(res))
    return res

  def QueryNodes(self, req: QueryNodesRequest) -> QueryNodesResponse:
    self._log_request('query-nodes', req)
    # Calls ReadWorkPlan under the hood, with some limitations:
    # * Currently only supports the case where all queries are searching the
    # same Workplan.
    # * The checks will only be included in the result if the query-nodes
    # request specifies both `select_checks` and `collect_checks`.
    # * Stages and edits are not supported for now, just like the fake.
    # TODO(b/460826158): call `query-nodes` directly after QueryNodes is ready
    # at the server side.
    read_req = self._query_to_read_work_plan_request(req)
    read_response = self._read_work_plan(read_req)
    res = self._filter_read_work_plan_responses(req, read_response)
    LOG.info('query-nodes response: %s', jsonpb.MessageToJson(res))
    return res

  def ReadWorkPlan(self, req: ReadWorkPlanRequest) -> ReadWorkPlanResponse:
    self._log_request('read-workplan', req)
    ret = self._run_cmd('read-workplan', req.SerializeToString())
    res = ReadWorkPlanResponse()
    res.ParseFromString(ret)
    LOG.info('read-workplan response: %s', jsonpb.MessageToJson(res))
    return res

  def _run_cmd(self, sub_cmd: str, req: bytes) -> bytes:
    cmd = [TURBOCI, sub_cmd, '--endpoint', self.endpoint]

    try:
      proc = subprocess.run(cmd, input=req, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
      LOG.error('failed with retcode %d', e.returncode)
      LOG.error('stderr: %s', e.stderr)
      raise
    return proc.stdout

  def _log_request(self, name: str, req: Message):
    """Redacts token and logs the request."""
    req_copy = req.__class__()
    req_copy.CopyFrom(req)
    if hasattr(req_copy, 'token') and req_copy.token:
      req_copy.token = '<redacted>'
    LOG.info('%s request: %s', name, jsonpb.MessageToJson(req_copy))

  # functions to make QueryNodes to call ReadWorkplan under the hood.
  def _query_to_read_work_plan_request(
      self, req: QueryNodesRequest) -> ReadWorkPlanRequest:
    # Extracts workplan id from the queries.
    wp_id = self._workplan_id_from_query_request(req)

    # Convert request.
    read_req = ReadWorkPlanRequest(workplan_id=wp_id)
    if req.HasField('token'):
      read_req.token = req.token

    self._infer_read_workplan_args(req, read_req)
    return read_req

  def _workplan_id_from_query_request(
      self, req: QueryNodesRequest) -> identifier.WorkPlan:
    wp_id = None

    def set_wp_id(new_wp_id):
      nonlocal wp_id
      if not wp_id:
        wp_id = new_wp_id
      elif wp_id != new_wp_id:
        raise NotImplementedError(
            'QueryNodes with multiple workplans is not supported')

    for query in req.query:
      node_set_type = query.WhichOneof('node_set')
      if node_set_type == 'nodes_in_workplan':
        set_wp_id(query.nodes_in_workplan)
      elif node_set_type == 'nodes_by_id':
        for node in query.nodes_by_id.nodes:
          node_type = node.WhichOneof('type')
          inner_node = getattr(node, node_type)
          set_wp_id(inner_node.work_plan)
      else:
        raise NotImplementedError(
            f'QueryNodes with node_set type {node_set_type} is not supported')

    if not wp_id or wp_id.id == '':
      raise ValueError('Failed to extract workplan id from QueryNodesRequest.')
    return wp_id

  def _infer_read_workplan_args(self, query_req: QueryNodesRequest,
                                read_req: ReadWorkPlanRequest):
    wants_checks = False
    wants_check_options = False
    wants_check_results = False

    for q in query_req.query:
      # Check requirements
      if q.HasField("select_checks") or q.HasField("collect_checks"):
        wants_checks = True
        if q.HasField("collect_checks"):
          if q.collect_checks.options:
            wants_check_options = True
          if q.collect_checks.result_data:
            wants_check_results = True
          if q.collect_checks.HasField("edits"):
            raise NotImplementedError('QueryNodes with edits is not supported')

      # Stage requirements
      if q.HasField("select_stages") or q.HasField("collect_stages"):
        raise NotImplementedError('QueryNodes with stages is not supported')

      # Extrapolates edge cases strictly requested by ID targeting
      if q.HasField("nodes_by_id"):
        for node in q.nodes_by_id.nodes:
          kind = node.WhichOneof("type")
          if kind in ("check", "check_result"):
            wants_checks = True
          elif kind == "check_edit":
            raise NotImplementedError('QueryNodes with edits is not supported')
          elif kind == "stage":
            raise NotImplementedError('QueryNodes with stages is not supported')
          elif kind == "stage_attempt":
            raise NotImplementedError('QueryNodes with stages is not supported')
          elif kind == "stage_edit":
            raise NotImplementedError('QueryNodes with stages is not supported')

    if wants_checks:
      read_req.included_node_types.append(identifier_kind.IDENTIFIER_KIND_CHECK)

    if query_req.HasField("type_info"):
      read_req.value_filter.type_info.CopyFrom(query_req.type_info)

    val_type = VALUE_MASK_VALUE_TYPE

    if wants_check_options:
      read_req.value_filter.check_options = val_type

    if wants_check_results:
      read_req.value_filter.check_result_data = val_type

  def _read_work_plan(self, req: ReadWorkPlanRequest) -> ReadWorkPlanResponse:
    res = ReadWorkPlanResponse()
    first_page = True

    while True:
      read_resp = self.ReadWorkPlan(req)

      if first_page:
        res.workplan.CopyFrom(read_resp.workplan)
        first_page = False
      else:
        res.workplan.stages.extend(read_resp.workplan.stages)
        res.workplan.checks.extend(read_resp.workplan.checks)

      # Merge Context Values globally
      for digest, v_data in read_resp.value_data.items():
        res.value_data[digest].CopyFrom(v_data)

      if read_resp.HasField("current_attempt_state"):
        res.current_attempt_state.CopyFrom(read_resp.current_attempt_state)

      if read_resp.HasField("version"):
        res.version.CopyFrom(read_resp.version)

      if read_resp.pagination_token:
        res.pagination_token = read_resp.pagination_token
      else:
        break

    return res

  def _filter_read_work_plan_responses(
      self, req: QueryNodesRequest,
      read_res: ReadWorkPlanResponse) -> QueryNodesResponse:
    query_resp = QueryNodesResponse()

    if read_res.HasField("workplan"):
      # Copies the WorkPlan block so we can prune it safely
      wp = query_resp.workplans.add()
      wp.CopyFrom(read_res.workplan)

      # Evaluates Checks against all queries collectively
      valid_checks = []
      for c in wp.checks:
        if any(self._check_is_selected_by_query(c, q) for q in req.query):
          valid_checks.append(c)

      del wp.checks[:]
      wp.checks.extend(valid_checks)

    # Propagates context values
    for digest, v_data in read_res.value_data.items():
      query_resp.value_data[digest].CopyFrom(v_data)

    if read_res.HasField("current_attempt_state"):
      query_resp.current_attempt_state.CopyFrom(read_res.current_attempt_state)

    if read_res.HasField("version"):
      query_resp.version.CopyFrom(read_res.version)

    return query_resp

  def _check_is_selected_by_query(self, check: Check, q: Query) -> bool:
    if q.HasField("nodes_by_id"):
      for node in q.nodes_by_id.nodes:
        if node.WhichOneof(
            "type") == "check" and node.check.id == check.identifier.id:
          return True
      return False

    elif q.HasField("nodes_in_workplan"):
      if not q.HasField("collect_checks") or not q.HasField("select_checks"):
        return False
      return self._check_matches_select(check, q.select_checks)

    return False

  def _check_matches_select(self, check: Check,
                            select_checks: Query.SelectChecks):
    if len(select_checks.predicates) == 0:
      return True  # Empty predicates list means all checks match.

    for p in select_checks.predicates:
      match = True

      if p.HasField("kind") and check.kind != p.kind:
        match = False

      if match and p.HasField("state") and check.state != p.state:
        match = False

      if match and p.HasField("with_option_type"):
        pat = type_set_to_re(p.with_option_type)
        match = any(want_value_ref(pat, opt) for opt in check.options)

      if match and p.HasField("with_result_data_type"):
        pat = type_set_to_re(p.with_result_data_type)
        match = any(
            want_value_ref(pat, d) for r in check.results for d in r.data)

      if match:
        return True  # Matched at least one predicate (OR logic)

    return False
