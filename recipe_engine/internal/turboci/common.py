# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Implements internal details of the engine's TurboCI integration."""

from __future__ import annotations

import collections.abc

from typing import Iterable, Literal, Protocol, Sequence, Type, TypeVar, cast

from google.protobuf.message import Message

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.query_nodes_response import QueryNodesResponse
from PB.turboci.graph.orchestrator.v1.type_info import TypeInfo
from PB.turboci.graph.orchestrator.v1.workplan import WorkPlan
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.orchestrator.v1.write_nodes_response import WriteNodesResponse

from .ids import collect_check_ids, type_url_for, type_set, check_id, stage_id, to_id
from recipe_engine.internal.turboci import ids


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


def dep_group(*contained: str | identifier.Identifier | identifier.Check
              | identifier.Stage | WriteNodesRequest.DependencyGroup,
              stages: Sequence[str] = (),
              threshold: int = 0,
              in_workplan: str = "") -> WriteNodesRequest.DependencyGroup:
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
  ret = WriteNodesRequest.DependencyGroup()

  for obj in contained:
    match obj:
      case WriteNodesRequest.DependencyGroup():
        ret.groups.append(obj)
      case identifier.Identifier():
        match (typ := obj.WhichOneof('type')):
          case 'check':
            ret.edges.add(check=Edge.Check(identifier=obj.check))
          case 'stage':
            ret.edges.add(stage=Edge.Stage(identifier=obj.stage))
          case _:
            raise ValueError(f'Cannot create a dependency on target of kind {typ!r}')
      case identifier.Check():
        ret.edges.add(check=Edge.Check(identifier=obj))
      case identifier.Stage():
        ret.edges.add(stage=Edge.Stage(identifier=obj))
      case str():
        ret.edges.add(check=Edge.Check(
            identifier=check_id(obj, in_workplan=in_workplan)))

  for stage_bare in stages:
    ret.edges.add(stage=Edge.Stage(identifier=stage_id(stage_bare, in_workplan=in_workplan)))

  if threshold > (N := len(contained) + len(stages)):
    raise ValueError(
        'dep_group: threshold greater than contained edges+groups: '
        f'{threshold} > {N}')
  if threshold > 0:
    ret.threshold = threshold
  if threshold < 0:
    raise ValueError(f"dep_group: negative threshold {threshold}")

  return ret


def reason(message: str, *details: Message) -> WriteNodesRequest.Reason:
  """Helper to generate a WriteNodesRequest.Reason for WriteNodes."""
  ret = WriteNodesRequest.Reason(message=message)
  for detail in details:
    a = ret.details.add()
    a.data.Pack(detail, deterministic=True)
  return ret


CheckKindType = (
  CheckKind|
  Literal['CHECK_KIND_SOURCE', 'CHECK_KIND_BUILD', 'CHECK_KIND_TEST', 'CHECK_KIND_ANALYSIS']
)

CheckStateType = (
  CheckState|
  Literal['CHECK_STATE_PLANNING', 'CHECK_STATE_PLANNED', 'CHECK_STATE_WAITING', 'CHECK_STATE_FINAL']
)


def check(
    id: str,
    *,
    kind: CheckKindType = CheckKind.CHECK_KIND_UNKNOWN,
    state: CheckStateType = CheckState.CHECK_STATE_UNKNOWN,
    options: Sequence[Message] = (),
    deps: WriteNodesRequest.DependencyGroup | None = None,
    results: Sequence[Message] = (),
    finalize_results: bool = False,

    # Not needed for fake.
    in_workplan: str = "",
    realm: str | None = None,
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
      ret.kind = cast(CheckKind, CheckKind.Value(kind))
    else:
      ret.kind = kind

  if state:
    if isinstance(state, str):
      ret.state = cast(CheckState, CheckState.Value(state))
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
    el = ret.results.add()
    el.data.Pack(rslt, deterministic=True)

  for realm, rslt in realm_results:
    el = ret.results.add(realm=realm)
    el.data.Pack(rslt, deterministic=True)

  return ret


def write_nodes(
    *atoms: WriteNodesRequest.CheckWrite | WriteNodesRequest.StageWrite
    | WriteNodesRequest.Reason,
    current_stage: WriteNodesRequest.CurrentStageWrite | None = None,
    current_attempt: WriteNodesRequest.CurrentAttemptWrite | None = None,
    txn: WriteNodesRequest.TransactionDetails | None = None,
    client: TurboCIClient | None = None,
) -> WriteNodesResponse:
  """Convenience function for client.WriteNodes.

  At least one Reason is required. If more than one is provided, they will be
  merged sequentially in the order provided in `atoms`.

  Also see `check` and `reason` to help generate CheckWrite and Reason messages.
  """
  req = WriteNodesRequest(
      current_stage=current_stage,
      current_attempt=current_attempt,
      txn=txn,
  )
  for atom in atoms:
    match atom:
      case WriteNodesRequest.CheckWrite():
        req.checks.append(atom)
      case WriteNodesRequest.StageWrite():
        req.stages.append(atom)
      case WriteNodesRequest.Reason():
        req.reason.MergeFrom(atom)
      case _:
        raise TypeError(f'write_nodes: unknown atom {type(atom)}')
  if not req.reason:
    raise ValueError('A reason is required for write_nodes.')
  return (client or CLIENT).WriteNodes(req)


# NodesInWorkplan is a QueryNodeSet which selects from all nodes in the
# current workplan.
NodesInWorkplan = identifier.WorkPlan()


QueryNodeSet = (
  identifier.WorkPlan|
  Query.NodesByID|
  Query.NodesAcrossWorkPlans|
  Iterable[ids.AnyIdentifier]
)

QuerySelectAtom = (
  Query.SelectChecks|
  Query.SelectChecks.Predicate|
  Query.SelectStages|
  Query.SelectStages.Predicate
)

QueryExpandAtom = (
  Query.ExpandDependencies|
  Query.ExpandDependents
)

QueryCollectAtom = (
  Query.CollectChecks|
  Query.CollectStages
)

QueryAtoms = (
  QuerySelectAtom|
  QueryExpandAtom|
  QueryCollectAtom
)


def make_query(*atoms: QueryAtoms | None, node_set: QueryNodeSet = NodesInWorkplan) -> Query:
  """Convenience function to make a Query message from atomic bits.

  None atoms are skipped.

  All given atoms are merged into a single Query.

  Repeated fields are appended (e.g. CheckPattern and StagePattern).
  """
  ret = Query()
  match node_set:
    case identifier.WorkPlan():
      ret.nodes_in_workplan.CopyFrom(node_set)
    case Query.NodesByID():
      ret.nodes_by_id.CopyFrom(node_set)
    case Query.NodesAcrossWorkPlans():
      ret.nodes_across_workplans.CopyFrom(node_set)
    case collections.abc.Iterable():
      ret.nodes_by_id.nodes.extend(
          ids.wrap_id(x) for x in node_set
      )
    case _:
      raise TypeError(f'make_query: unknown node_set {type(node_set)}')

  for atom in atoms:
    if atom is None:
      continue
    match atom:
    # QuerySelectAtom
      case Query.SelectChecks():
        ret.select_checks.MergeFrom(atom)
      case Query.SelectChecks.Predicate():
        ret.select_checks.predicates.append(atom)
      case Query.SelectStages():
        ret.select_stages.MergeFrom(atom)
      case Query.SelectStages.Predicate():
        ret.select_stages.predicates.append(atom)

      # QueryExpandAtom
      case Query.ExpandDependencies():
        ret.expand_dependencies.MergeFrom(atom)
      case Query.ExpandDependents():
        ret.expand_dependents.MergeFrom(atom)

      # QueryCollectAtom
      case Query.CollectChecks():
        ret.collect_checks.MergeFrom(atom)
      case Query.CollectStages():
        ret.collect_stages.MergeFrom(atom)

      case _:
        raise TypeError(f'make_query: unknown atom {type(atom)}')

  return ret


def query_nodes(
    *queries: Query,
    version: QueryNodesRequest.VersionRestriction | None = None,
    types: Sequence[str | Message | type[Message]] = (),
    client: TurboCIClient | None = None,
) -> QueryNodesResponse:
  """Convenience function for CLIENT.QueryNodes."""
  return (client or CLIENT).QueryNodes(
      QueryNodesRequest(
          version=version,
          query=queries,
          type_info=TypeInfo(wanted=type_set(*types)),
      ))


def read_checks(*ids: identifier.Check | str,
                collect: Query.CollectChecks | None = None,
                types: Sequence[str | Message | type[Message]] = (),
                client: TurboCIClient | None = None) -> Sequence[Check]:
  """Convenience function for reading one or more checks by ID.

  This just does a query_nodes for the ids specified by `ids`, and then unwraps
  the result.
  """
  idents = list(collect_check_ids(*ids))
  work_plan = {ident.check.work_plan.id for ident in idents}
  if len(work_plan) > 1:
    raise ValueError(
        f'read_checks: got checks from more than one workplan: {work_plan}')

  checks = query_nodes(
      make_query(
          collect,
          node_set=idents,
      ), types=types, client=client).workplans[0].checks
  return checks


MsgT = TypeVar('MsgT', bound=Message)


def get_check_by_short_id(workplan: WorkPlan, check_id: str) -> Check:
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


def get_check_by_full_id(workplan: WorkPlan, check_id: str) -> Check:
  """Finds and returns the Check for the check whose identifier's string
  representation (e.g. 'L12345:C123') is `check_id`.

  If this check is not found, returns None."""
  return get_check_by_short_id(workplan, to_id(check_id).check.id)


def get_option(msg: Type[MsgT], check: Check) -> MsgT | None:
  """Extracts, unpacks and returns the data for the proto message `msg`
  from the check's option_data.

  If the check does not have a matching option, returns None.

  Example:

    dat = get_option(MyMessage, graph.checks['foo'])
    # dat is None or an instance of MyMessage
  """
  url = type_url_for(msg)
  for option in check.options:
    if option.type_url == url:
      ret = msg()
      option.inline.binary.Unpack(ret)
      return ret
  return None


def get_results(msg: Type[MsgT], check: Check) -> list[MsgT]:
  """Extracts, unpacks and returns the data for the proto message `msg`
  from all results in the check.

  If the check doesn't have any result data which matches `msg`, returns an
  empty list.

  Example:

    dat = get_results(MyMessage, graph.checks['foo'])
    # dat is a possibly-empty list of instances of MyMessage
  """
  url = type_url_for(msg)
  ret: list[MsgT] = []
  for result in check.results:
    for dat in result.data:
      if dat.type_url == url:
        val = msg()
        dat.inline.binary.Unpack(val)
        ret.append(val)
  return ret
