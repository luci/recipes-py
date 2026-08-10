# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Util functions for TurboCI query translation, execution, and filtering."""

from __future__ import annotations

import re
from typing import Callable

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.ids.v1 import identifier_kind
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import (
    QueryNodesRequest,
)
from PB.turboci.graph.orchestrator.v1.query_nodes_response import (
    QueryNodesResponse,
)
from PB.turboci.graph.orchestrator.v1.read_workplan_request import (
    ReadWorkPlanRequest,
)
from PB.turboci.graph.orchestrator.v1.read_workplan_response import (
    ReadWorkPlanResponse,
)
from PB.turboci.graph.orchestrator.v1.type_set import TypeSet
from PB.turboci.graph.orchestrator.v1.value_mask import VALUE_MASK_VALUE_TYPE
from PB.turboci.graph.orchestrator.v1.value_ref import ValueRef


def type_set_to_re(ts: TypeSet) -> re.Pattern:
  fragments: list[str] = []
  for frag in ts.type_urls:
    q = re.escape(frag)
    if q.endswith(r'\*'):
      fragments.append(q.removesuffix(r'\*') + '.*')
    else:
      fragments.append(q)

  return re.compile(f'({")|(".join(fragments)})')


def want_value_ref(pat: re.Pattern, value_ref: ValueRef) -> bool:
  return bool(pat.match(value_ref.type_url))


def workplan_id_from_query_request(
    req: QueryNodesRequest,
) -> identifier.WorkPlan | None:
  wp_id = None
  first_query = True

  def set_wp_id(new_wp_id):
    nonlocal wp_id
    nonlocal first_query
    if first_query:
      if new_wp_id and new_wp_id.id:
        wp_id = new_wp_id
      first_query = False
      return

    if not first_query:
      if wp_id != new_wp_id:
        raise NotImplementedError(
            'QueryNodes with multiple workplans is not supported'
        )

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
          f'QueryNodes with node_set type {node_set_type} is not supported'
      )

  return wp_id


def infer_read_workplan_args(
    query_req: QueryNodesRequest,
    read_req: ReadWorkPlanRequest,
) -> None:
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
        elif kind in ("stage", "stage_attempt", "stage_edit"):
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


def query_to_read_work_plan_request(
    req: QueryNodesRequest,
) -> ReadWorkPlanRequest:
  """Translates a QueryNodesRequest to an equivalent ReadWorkPlanRequest."""
  wp_id = workplan_id_from_query_request(req)

  read_req = ReadWorkPlanRequest()
  if wp_id and wp_id.id:
    read_req.workplan_id.CopyFrom(wp_id)

  if req.HasField('token'):
    read_req.token = req.token

  infer_read_workplan_args(req, read_req)
  return read_req


def check_matches_select(
    check: Check,
    select_checks: Query.SelectChecks,
) -> bool:
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
          want_value_ref(pat, d) for r in check.results for d in r.data
      )

    if match:
      return True  # Matched at least one predicate (OR logic)

  return False


def check_is_selected_by_query(check: Check, q: Query) -> bool:
  if q.HasField("nodes_by_id"):
    for node in q.nodes_by_id.nodes:
      if (
          node.WhichOneof("type") == "check"
          and node.check.id == check.identifier.id
      ):
        return True
    return False

  elif q.HasField("nodes_in_workplan"):
    if not q.HasField("collect_checks") or not q.HasField("select_checks"):
      return False
    return check_matches_select(check, q.select_checks)

  return False


def filter_read_work_plan_responses(
    req: QueryNodesRequest,
    read_res: ReadWorkPlanResponse,
) -> QueryNodesResponse:
  """Filters a ReadWorkPlanResponse against the criteria in
  QueryNodesRequest.
  """
  query_resp = QueryNodesResponse()

  if read_res.HasField("workplan"):
    # Copies the WorkPlan block so we can prune it safely
    wp = query_resp.workplans.add()
    wp.CopyFrom(read_res.workplan)

    # Evaluates Checks against all queries collectively
    valid_checks = []
    for c in wp.checks:
      if any(check_is_selected_by_query(c, q) for q in req.query):
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


def paginate_read_work_plan(
    read_fn: Callable[[ReadWorkPlanRequest], ReadWorkPlanResponse],
    req: ReadWorkPlanRequest,
) -> ReadWorkPlanResponse:
  """Consolidates paginated ReadWorkPlanResponse objects into a single
  response.
  """
  res = ReadWorkPlanResponse()
  first_page = True

  while True:
    read_resp = read_fn(req)

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
