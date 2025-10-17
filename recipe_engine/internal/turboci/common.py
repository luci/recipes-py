# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Implements internal details of the engine's TurboCI integration."""

from __future__ import annotations

from typing import Literal, Protocol, Sequence

from google.protobuf.message import Message

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.check_view import CheckView
from PB.turboci.graph.orchestrator.v1.edge_group import EdgeGroup
from PB.turboci.graph.orchestrator.v1.graph_view import GraphView
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.query_nodes_response import QueryNodesResponse
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.orchestrator.v1.write_nodes_response import WriteNodesResponse

from .ids import collect_check_ids, type_urls, wrap_id, check_id, stage_id


class TurboCIClient(Protocol):

  def WriteNodes(self, req: WriteNodesRequest) -> WriteNodesResponse:
    ...

  def QueryNodes(self, req: QueryNodesRequest) -> QueryNodesResponse:
    ...


# CLIENT is the global injection point for the currently-active TurboCIClient.
#
# write_nodes, query_nodes and read_checks in this file default to this.
#
# It's initialized by the recipe engine startup routine, and also on
# a per-test-case basis during simulation and debugging.
CLIENT: TurboCIClient


def edge_group(*contained: str|identifier.Identifier|identifier.Check|identifier.Stage|EdgeGroup,
              stages: Sequence[str] = (), threshold: int = 0, in_workplan: str = "") -> EdgeGroup:
  """Helper to generate an EdgeGroup for WriteNodes.

  You may pass:
    * strings which will be interpreted as a BARE check ids, and will be
      converted to identifier.Checks via `check_id` along with `in_workplan`.
      These will be added as edges to the returned group.
    * `stages` works similarly to passing bare check ids and will be converted
      to identifier.Stages. Note that the `N` or `S` prefix is required for
      these IDs.
    * identifier.Identifier (which must be a Check) or identifier.Check. These
      will be added as edges to the returned group.
    * EdgeGroups (possibly returned via another edge_group call) which will be
      added as sub-groups.

  Threshold defaults to 0 (i.e. all contained edges and groups must be satisfied
  for this group to be satisfied), but you can set it to another value with the
  threshold keyword arg.
  """
  ret = EdgeGroup()
  if threshold > 0:
    ret.threshold = threshold
  if threshold < 0:
    raise ValueError(f"edge_group: negative threshold {threshold}")

  for obj in contained:
    match obj:
      case EdgeGroup():
        ret.groups.append(obj)
      case identifier.Identifier():
        if (typ := obj.WhichOneof('type')) not in ('check', 'stage'):
          raise ValueError(f'Cannot create a dependency on target of kind {typ!r}')
        ret.edges.add(target=obj)
      case identifier.Check():
        ret.edges.add(target=wrap_id(obj))
      case identifier.Stage():
        ret.edges.add(target=wrap_id(obj))
      case str():
        ret.edges.add(target=wrap_id(check_id(obj, in_workplan=in_workplan)))

  for stage_bare in stages:
    ret.edges.add(target=wrap_id(stage_id(stage_bare, in_workplan=in_workplan)))

  return ret


def reason(reason: str, *details: Message, realm: str|None = None) -> WriteNodesRequest.Reason:
  """Helper to generate a WriteNodesRequest.Reason for WriteNodes."""
  ret = WriteNodesRequest.Reason(reason=reason, realm=realm)
  for detail in details:
    a = ret.details.add()
    a.Pack(detail, deterministic=True)
  return ret


CheckKindType = (
  CheckKind|
  Literal['SOURCE', 'BUILD', 'TEST', 'ANALYSIS']|
  Literal['CHECK_KIND_SOURCE', 'CHECK_KIND_BUILD', 'CHECK_KIND_TEST', 'CHECK_KIND_ANALYSIS']
)

CheckStateType = (
  CheckState|
  Literal['PLANNING', 'PLANNED', 'WAITING', 'FINAL']|
  Literal['CHECK_STATE_PLANNING', 'CHECK_STATE_PLANNED', 'CHECK_STATE_WAITING', 'CHECK_STATE_FINAL']
)


def check(
    id: str,

    *,
    kind: CheckKindType = CheckKind.CHECK_KIND_UNKNOWN,
    state: CheckStateType = CheckState.CHECK_STATE_UNKNOWN,
    options: Sequence[Message] = (),
    deps: Sequence[EdgeGroup]|None = None,
    results: Sequence[Message] = (),
    finalize_results: bool = False,

    # Not needed for fake.
    in_workplan: str = "",
    realm: str|None = None,
    realm_options: Sequence[tuple[str, Message]] = (),
    realm_results: Sequence[tuple[str, Message]] = (),
) -> WriteNodesRequest.CheckWrite:
  """Helper to generate a CheckWrite for client.WriteNodes.

  Notes:
    * in_workplan is optional - a CheckWrite will assume by default that an
      empty workplan id means "in the current workplan".
    * realm (and realm_*) are optional - a CheckWrite will assume the same realm
      as the current recipe execution context by default.
    * If using both `options` and `realm_options` (or their results
      counterparts), there must not be duplicates on the packed type urls. That
      is, for some given type 'types.googleapis.com/foo.FooMsg', it cannot occur
      in BOTH `options` and `realm_options`.
  """
  ret = WriteNodesRequest.CheckWrite(realm=realm)
  ret.identifier.CopyFrom(check_id(id, in_workplan=in_workplan))

  if kind:
    if isinstance(kind, str):
      kind = {
        'SOURCE': CheckKind.CHECK_KIND_SOURCE,
        'BUILD': CheckKind.CHECK_KIND_BUILD,
        'TEST': CheckKind.CHECK_KIND_TEST,
        'ANALYSIS': CheckKind.CHECK_KIND_ANALYSIS,
      }[kind]
    ret.kind = kind

  if state:
    if isinstance(state, str):
      state = {
        'PLANNING': CheckState.CHECK_STATE_PLANNING,
        'PLANNED': CheckState.CHECK_STATE_PLANNED,
        'WAITING': CheckState.CHECK_STATE_WAITING,
        'FINAL': CheckState.CHECK_STATE_FINAL,
      }[state]
    ret.state = state

  if finalize_results:
    ret.finalize_results = finalize_results

  if deps:
    ret.dependencies.extend(deps)

  for opt in options:
    el = ret.options.add()
    el.value.Pack(opt, deterministic=True)

  for realm, opt in realm_options:
    el = ret.options.add(realm=realm)
    el.value.Pack(opt, deterministic=True)

  for rslt in results:
    el = ret.results.add()
    el.value.Pack(rslt, deterministic=True)

  for realm, rslt in realm_results:
    el = ret.results.add(realm=realm)
    el.value.Pack(rslt, deterministic=True)

  return ret


def write_nodes(
    *atoms: WriteNodesRequest.CheckWrite|WriteNodesRequest.StageWrite|WriteNodesRequest.Reason,

    current_stage: WriteNodesRequest.CurrentStageWrite|None = None,
    txn: WriteNodesRequest.TransactionDetails|None = None,
    client: TurboCIClient|None = None,
) -> WriteNodesResponse:
  """Convenience function for client.WriteNodes.

  At least one Reason is required.

  Also see `check` and `reason` to help generate CheckWrite and Reason messages.
  """
  req = WriteNodesRequest(
      current_stage=current_stage,
      txn=txn,
  )
  for atom in atoms:
    match atom:
      case WriteNodesRequest.CheckWrite():
        req.checks.append(atom)
      case WriteNodesRequest.StageWrite():
        req.stages.append(atom)
      case WriteNodesRequest.Reason():
        req.reasons.append(atom)
      case _:
        raise TypeError(f'write_nodes: unknown atom {type(atom)}')
  if not req.reasons:
    raise ValueError('At least one reason is require for write_nodes.')
  return (client or CLIENT).WriteNodes(req)


QuerySelectAtom = (
  Query.Select|
  Query.Select.WorkPlanConstraint|
  Query.Select.CheckPattern|
  Query.Select.StagePattern
)

QueryExpandAtom = (
  Query.Expand|
  Query.Expand.Dependencies
)

QueryCollectAtom = (
  Query.Collect|
  Query.Collect.Check|
  Query.Collect.Stage
)

QueryAtoms = (
  QuerySelectAtom|
  QueryExpandAtom|
  QueryCollectAtom
)


def make_query(
    *atoms: QueryAtoms|None,
    types: Sequence[str|Message|type[Message]] = (),
) -> Query:
  """Convenience function to make a Query message from atomic bits.

  None atoms are skipped.

  All given atoms are merged into a single Query.

  Repeated fields are appended (e.g. CheckPattern and StagePattern).
  """
  ret = Query(type_urls=type_urls(*types))
  for atom in atoms:
    if atom is None:
      continue
    match atom:
      # QuerySelectAtom
      case Query.Select():
        ret.select.MergeFrom(atom)
      case Query.Select.WorkPlanConstraint():
        ret.select.workplan.MergeFrom(atom)
      case Query.Select.CheckPattern():
        ret.select.check_patterns.append(atom)
      case Query.Select.StagePattern():
        ret.select.stage_patterns.append(atom)

      # QueryExpandAtom
      case Query.Expand():
        ret.expand.MergeFrom(atom)
      case Query.Expand.Dependencies():
        ret.expand.dependencies.MergeFrom(atom)

      # QueryCollectAtom
      case Query.Collect():
        ret.collect.MergeFrom(atom)
      case Query.Collect.Check():
        ret.collect.check.MergeFrom(atom)
      case Query.Collect.Stage():
        ret.collect.stage.MergeFrom(atom)

      case _:
        raise TypeError(f'make_query: unknown atom {type(atom)}')

  return ret


def query_nodes(
    *queries: Query,
    version: QueryNodesRequest.VersionRestriction|None = None,
    client: TurboCIClient|None = None,
) -> GraphView:
  """Convenience function for CLIENT.QueryNodes."""
  return (client or CLIENT).QueryNodes(QueryNodesRequest(
      version=version,
      query=queries,
  )).graph


def read_checks(*ids: identifier.Check|str,
                collect: Query.Collect.Check|None = None,
                types: Sequence[str|Message|type[Message]] = (),
                client: TurboCIClient|None = None) -> Sequence[CheckView]:
  """Convenience function for reading one or more checks by ID.

  This just does a query_nodes for the ids specified by `ids`, and then unwraps
  the result.
  """
  return query_nodes(make_query(
      Query.Select(nodes=collect_check_ids(*ids)),
      collect,
      types=types,
  ), client=client).checks
