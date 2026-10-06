# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Implements internal details of the engine's TurboCI integration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal, Protocol, TypeVar, cast

from google.protobuf import message
from turboci.utils import ids, value

from PB.turboci.graph.ids.v1 import identifier as identifier_pb
from PB.turboci.graph.orchestrator.v1 import check as check_pb
from PB.turboci.graph.orchestrator.v1 import check_kind as check_kind_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import edge as edge_pb
from PB.turboci.graph.orchestrator.v1 import query as query_pb
from PB.turboci.graph.orchestrator.v1 import (
    query_nodes_request as query_nodes_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    query_nodes_response as query_nodes_response_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    read_workplan_request as read_workplan_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    read_workplan_response as read_workplan_response_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    transaction_details as transaction_details_pb,
)
from PB.turboci.graph.orchestrator.v1 import type_info as type_info_pb
from PB.turboci.graph.orchestrator.v1 import type_set as type_set_pb
from PB.turboci.graph.orchestrator.v1 import workplan as workplan_pb
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_request as write_nodes_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_response as write_nodes_response_pb,
)


class TurboCIClient(Protocol):

  def WriteNodes(
      self, req: write_nodes_request_pb.WriteNodesRequest
  ) -> write_nodes_response_pb.WriteNodesResponse:
    ...

  def QueryNodes(
      self, req: query_nodes_request_pb.QueryNodesRequest
  ) -> query_nodes_response_pb.QueryNodesResponse:
    ...

  def ReadWorkPlan(
      self, req: read_workplan_request_pb.ReadWorkPlanRequest
  ) -> read_workplan_response_pb.ReadWorkPlanResponse:
    ...


# CLIENT is the global injection point for the currently-active TurboCIClient.
#
# write_nodes, query_nodes and read_checks in this file default to this.
#
# It's initialized by the recipe engine startup routine, and also on
# a per-test-case basis during simulation and debugging.
CLIENT: TurboCIClient


def dep_group(
    *contained: (
        str
        | identifier_pb.Identifier
        | identifier_pb.Check
        | identifier_pb.Stage
        | write_nodes_request_pb.WriteNodesRequest.DependencyGroup
    ),
    stages: Sequence[str] = (),
    threshold: int = 0,
    in_workplan: str = "",
) -> write_nodes_request_pb.WriteNodesRequest.DependencyGroup:
  """Helper to generate a WriteNodesRequest.DependencyGroup.

  You may pass:
    * strings which will be interpreted as a BARE check ids, and will be
      converted to identifier.Checks via `check_id` along with `in_workplan`.
      These will be added as edges to the returned group.
    * `stages` works similarly to passing bare check ids and will be converted
      to identifier.Stages. Note that the `N` or `S` prefix is required for
      these IDs.
    * identifier.Identifier (which must be a Check) or identifier.Check. These
      will be added as edges to the returned group.
    * EdgeGroups (possibly returned via another dep_group call) which will be
      added as sub-groups.

  Threshold defaults to 0 (i.e. all contained edges and groups must be satisfied
  for this group to be satisfied), but you can set it to another value with the
  threshold keyword arg.
  """
  ret = write_nodes_request_pb.WriteNodesRequest.DependencyGroup()
  wp = ids.workplan(in_workplan) if in_workplan else None

  for obj in contained:
    match obj:
      case write_nodes_request_pb.WriteNodesRequest.DependencyGroup():
        ret.groups.append(obj)
      case identifier_pb.Identifier():
        match (typ := obj.WhichOneof('type')):
          case 'check':
            ret.edges.add(check=edge_pb.Edge.Check(identifier=obj.check))
          case 'stage':
            ret.edges.add(stage=edge_pb.Edge.Stage(identifier=obj.stage))
          case _:
            raise ValueError(
                f'Cannot create a dependency on target of kind {typ!r}'
            )
      case identifier_pb.Check():
        ret.edges.add(check=edge_pb.Edge.Check(identifier=obj))
      case identifier_pb.Stage():
        ret.edges.add(stage=edge_pb.Edge.Stage(identifier=obj))
      case str():
        ret.edges.add(check=edge_pb.Edge.Check(identifier=ids.check(obj, wp)))

  for stage_bare in stages:
    ret.edges.add(
        stage=edge_pb.Edge.Stage(identifier=ids.stage(stage_bare, wp))
    )

  if threshold > (N := len(contained) + len(stages)):
    raise ValueError(
        'dep_group: threshold greater than contained edges+groups: '
        f'{threshold} > {N}')
  if threshold > 0:
    ret.threshold = threshold
  if threshold < 0:
    raise ValueError(f"dep_group: negative threshold {threshold}")

  return ret


def reason(
    message: str, *details: message.Message
) -> write_nodes_request_pb.WriteNodesRequest.Reason:
  """Helper to generate a WriteNodesRequest.Reason for WriteNodes."""
  ret = write_nodes_request_pb.WriteNodesRequest.Reason(message=message)
  for detail in details:
    a = ret.details.add()
    a.data.Pack(detail, deterministic=True)
  return ret


CheckKindType = (
    check_kind_pb.CheckKind
    | Literal[
        'CHECK_KIND_SOURCE',
        'CHECK_KIND_BUILD',
        'CHECK_KIND_TEST',
        'CHECK_KIND_ANALYSIS',
    ]
)

CheckStateType = (
    check_state_pb.CheckState
    | Literal[
        'CHECK_STATE_PLANNING',
        'CHECK_STATE_PLANNED',
        'CHECK_STATE_WAITING',
        'CHECK_STATE_FINAL',
    ]
)


def check(
    id: str,
    *,
    kind: CheckKindType = check_kind_pb.CheckKind.CHECK_KIND_UNKNOWN,
    state: CheckStateType = check_state_pb.CheckState.CHECK_STATE_UNKNOWN,
    options: Sequence[message.Message] = (),
    deps: (
        write_nodes_request_pb.WriteNodesRequest.DependencyGroup | None
    ) = None,
    results: Sequence[message.Message] = (),
    finalize_results: bool = False,

    # Not needed for fake.
    in_workplan: str = "",
    realm: str | None = None,
    realm_options: Sequence[tuple[str, message.Message]] = (),
    realm_results: Sequence[tuple[str, message.Message]] = (),
) -> write_nodes_request_pb.WriteNodesRequest.CheckWrite:
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
  wp = ids.workplan(in_workplan) if in_workplan else None
  ret = write_nodes_request_pb.WriteNodesRequest.CheckWrite(realm=realm)
  ret.identifier.CopyFrom(ids.check(id, wp))

  if kind:
    if isinstance(kind, str):
      ret.kind = cast(
          check_kind_pb.CheckKind, check_kind_pb.CheckKind.Value(kind)
      )
    else:
      ret.kind = kind

  if state:
    if isinstance(state, str):
      ret.state = cast(
          check_state_pb.CheckState, check_state_pb.CheckState.Value(state)
      )
    else:
      ret.state = state

  if finalize_results:
    ret.finalize_results = finalize_results

  if deps:
    ret.dependencies.CopyFrom(deps)

  for opt in options:
    el = ret.options.add()
    el.data.Pack(opt, deterministic=True)

  for realm, opt in realm_options:
    el = ret.options.add(realm=realm)
    el.data.Pack(opt, deterministic=True)

  for rslt in results:
    el = ret.result_data.add()
    el.data.Pack(rslt, deterministic=True)

  for realm, rslt in realm_results:
    el = ret.result_data.add(realm=realm)
    el.data.Pack(rslt, deterministic=True)

  return ret


def write_nodes(
    *atoms: (
        write_nodes_request_pb.WriteNodesRequest.CheckWrite
        | write_nodes_request_pb.WriteNodesRequest.StageWrite
        | write_nodes_request_pb.WriteNodesRequest.Reason
    ),
    current_stage: (
        write_nodes_request_pb.WriteNodesRequest.CurrentStageWrite | None
    ) = None,
    current_attempt: (
        write_nodes_request_pb.WriteNodesRequest.CurrentAttemptWrite | None
    ) = None,
    txn: transaction_details_pb.TransactionDetails | None = None,
    client: TurboCIClient | None = None,
) -> write_nodes_response_pb.WriteNodesResponse:
  """Convenience function for client.WriteNodes.

  At least one Reason is required. If more than one is provided, they will be
  merged sequentially in the order provided in `atoms`.

  Also see `check` and `reason` to help generate CheckWrite and Reason messages.
  """
  req = write_nodes_request_pb.WriteNodesRequest(
      current_stage=current_stage,
      current_attempt=current_attempt,
      txn=txn,
  )
  for atom in atoms:
    match atom:
      case write_nodes_request_pb.WriteNodesRequest.CheckWrite():
        req.checks.append(atom)
      case write_nodes_request_pb.WriteNodesRequest.StageWrite():
        req.stages.append(atom)
      case write_nodes_request_pb.WriteNodesRequest.Reason():
        req.reason.MergeFrom(atom)
      case _:
        raise TypeError(f'write_nodes: unknown atom {type(atom)}')
  if not req.reason:
    raise ValueError('A reason is required for write_nodes.')
  return (client or CLIENT).WriteNodes(req)


# NodesInWorkplan is a QueryNodeSet which selects from all nodes in the
# current workplan.
NodesInWorkplan = identifier_pb.WorkPlan()


QueryNodeSet = (
    identifier_pb.WorkPlan
    | query_pb.Query.NodesByID
    | query_pb.Query.NodesAcrossWorkPlans
    | Iterable[ids.AnyIdentifier]
)

QuerySelectAtom = (
    query_pb.Query.SelectChecks
    | query_pb.Query.SelectChecks.Predicate
    | query_pb.Query.SelectStages
    | query_pb.Query.SelectStages.Predicate
)

QueryExpandAtom = (
    query_pb.Query.ExpandDependencies
    | query_pb.Query.ExpandDependents
)

QueryCollectAtom = (
    query_pb.Query.CollectChecks
    | query_pb.Query.CollectStages
)

QueryAtoms = (
    QuerySelectAtom
    | QueryExpandAtom
    | QueryCollectAtom
)


def make_query(
    *atoms: QueryAtoms | None, node_set: QueryNodeSet = NodesInWorkplan
) -> query_pb.Query:
  """Convenience function to make a Query message from atomic bits.

  None atoms are skipped.

  All given atoms are merged into a single Query.

  Repeated fields are appended (e.g. CheckPattern and StagePattern).
  """
  ret = query_pb.Query()
  match node_set:
    case identifier_pb.WorkPlan():
      ret.nodes_in_workplan.CopyFrom(node_set)
    case query_pb.Query.NodesByID():
      ret.nodes_by_id.CopyFrom(node_set)
    case query_pb.Query.NodesAcrossWorkPlans():
      ret.nodes_across_workplans.CopyFrom(node_set)
    case Iterable():
      ret.nodes_by_id.nodes.extend(ids.wrap(x) for x in node_set)
    case _:
      raise TypeError(f'make_query: unknown node_set {type(node_set)}')

  for atom in atoms:
    if atom is None:
      continue
    match atom:
    # QuerySelectAtom
      case query_pb.Query.SelectChecks():
        ret.select_checks.MergeFrom(atom)
      case query_pb.Query.SelectChecks.Predicate():
        ret.select_checks.predicates.append(atom)
      case query_pb.Query.SelectStages():
        ret.select_stages.MergeFrom(atom)
      case query_pb.Query.SelectStages.Predicate():
        ret.select_stages.predicates.append(atom)

      # QueryExpandAtom
      case query_pb.Query.ExpandDependencies():
        ret.expand_dependencies.MergeFrom(atom)
      case query_pb.Query.ExpandDependents():
        ret.expand_dependents.MergeFrom(atom)

      # QueryCollectAtom
      case query_pb.Query.CollectChecks():
        ret.collect_checks.MergeFrom(atom)
      case query_pb.Query.CollectStages():
        ret.collect_stages.MergeFrom(atom)

      case _:
        raise TypeError(f'make_query: unknown atom {type(atom)}')

  return ret


def query_nodes(
    *queries: query_pb.Query,
    version: (
        query_nodes_request_pb.QueryNodesRequest.VersionRestriction | None
    ) = None,
    types: Sequence[str | message.Message | type[message.Message]] = (),
    client: TurboCIClient | None = None,
) -> query_nodes_response_pb.QueryNodesResponse:
  """Convenience function for CLIENT.QueryNodes."""
  return (client or CLIENT).QueryNodes(
      query_nodes_request_pb.QueryNodesRequest(
          version=version,
          query=queries,
          type_info=type_info_pb.TypeInfo(
              wanted=type_set_pb.TypeSet(
                  type_urls=[
                      x if isinstance(x, str) else value.url(x) for x in types
                  ]
              )
          ),
      )
  )


def read_checks(
    *idents: identifier_pb.Check | str,
    collect: query_pb.Query.CollectChecks | None = None,
    types: Sequence[str | message.Message | type[message.Message]] = (),
    client: TurboCIClient | None = None,
) -> list[check_pb.Check]:
  """Convenience function for reading one or more checks by ID.

  This just does a query_nodes for the ids specified by `idents`, and then
  unwraps the result.
  """
  wrapped: tuple[identifier_pb.Identifier, ...] = tuple(
      ids.wrap(x if isinstance(x, identifier_pb.Check) else ids.check(x))
      for x in idents
  )
  work_plan = {ident.check.work_plan.id for ident in wrapped}
  if len(work_plan) > 1:
    raise ValueError(
        f'read_checks: got checks from more than one workplan: {work_plan}')

  checks = query_nodes(
      make_query(
          collect,
          node_set=wrapped,
      ), types=types, client=client).workplans[0].checks
  return list(checks)


MsgT = TypeVar('MsgT', bound=message.Message)


def get_check_by_short_id(
    workplan: workplan_pb.WorkPlan, check_id: str
) -> check_pb.Check | None:
  """Finds and returns the Check for the check whose identifier.id is
  `check_id`.

  If this check is not found, returns None."""
  # TODO (b/483105203): Update data model to index checks and stages by ID to
  # allow O(1) lookup instead of O(N) lookup. Also remove other comments noting
  # the O(N) nature of this call in the files where it's used.
  for check in workplan.checks:
    if check.identifier.id == check_id:
      return check
  return None


def get_check_by_full_id(
    workplan: workplan_pb.WorkPlan, check_id: str
) -> check_pb.Check | None:
  """Finds and returns the Check for the check whose identifier's string
  representation (e.g. 'L12345:C123') is `check_id`.

  If this check is not found, returns None."""
  return get_check_by_short_id(workplan, ids.from_string(check_id).check.id)
