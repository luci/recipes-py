# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""
Implements an in-process version of the TurboCI Orchestrator service which hosts
a stateful workflow-global database.

In the future, this fake will be replaced with a full-fledged remote service
which can coordinate planning&results (Checks) and execution (Stages) across
different machines and services.

This fake just implements a local in-process graph database with only "Check"
node types.

A Check:
  - Has a simple state machine which restricts the mutability of the Check
    over time.
  - May have dependencies on other Checks which participate in the Check's
    state machine (e.g. the fake will automatically advance a Check from PLANNED
    to WAITING once the Check's dependencies are all FINAL).
  - Holds one or more arbitrarily-typed proto messages as 'options' which
    act as inputs to processes which produce results.
  - Holds one or more arbitrarily-typed proto messages as 'results' which
    are outputs for this particular Check, but may serve as additional inputs
    to processes attempting to resolve other Checks blocked on this one.

Subsets of the graph state can be serialized as proto to be passed to another
process.

The graph state in this process can also be bulk-updated from such a serialized
subset to allow an exported graph subset to be returned; however this
bulk-update will be lossy since there will be no central, synchronized, process
to reconcile edits. (Once the real remote service exists, it will be able to
allow many different processes to explicitly coordinate via edits to a single
graph. The bulk update functionality will just be to help model this in limited
contexts during the migration, e.g. when triggering one build from another).

This fake does NO security handling for the graph data which will be present
in the real service. Functionality described by the protos, but not implemented
by this fake, will raise NotImplementedError.
"""

from __future__ import annotations

from collections import defaultdict
import copy
import re
import time

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, TypeVar, cast

from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from google.protobuf.timestamp_pb2 import Timestamp

from PB.turboci.graph.ids.v1 import identifier

from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_view import CheckView
from PB.turboci.graph.orchestrator.v1.check_state import (
  CheckState, CHECK_STATE_PLANNING, CHECK_STATE_PLANNED, CHECK_STATE_WAITING,
  CHECK_STATE_FINAL)
from PB.turboci.graph.orchestrator.v1.check_view import CheckView
from PB.turboci.graph.orchestrator.v1.datum import Datum
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.graph_view import GraphView
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.query_nodes_response import QueryNodesResponse
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.transaction_invariant import TransactionConflictFailure
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.orchestrator.v1.write_nodes_response import WriteNodesResponse
from recipe_engine.internal.turboci import check_invariant
from recipe_engine.internal.turboci import edge
from recipe_engine.internal.turboci.errors import TransactionConflictException, InvalidArgumentException

from .ids import from_id, to_id, wrap_id
from .common import TurboCIClient


def _is_rev_newer(a: Revision, b: Revision) -> bool:
  return (a.ts.seconds, a.ts.nanos) > (b.ts.seconds, b.ts.nanos)


@dataclass
class _IndexEntrySnapshot:
  kind: CheckKind = CheckKind.CHECK_KIND_UNKNOWN
  state: CheckState = CheckState.CHECK_STATE_UNKNOWN
  option_types: set[str] = field(default_factory=set)
  result_types: set[str] = field(default_factory=set)
  deps: set[tuple[str, bool|None]] = field(default_factory=set)

  @staticmethod
  def for_check(check: Check|None) -> _IndexEntrySnapshot:
    if check is None:
      return _IndexEntrySnapshot()

    result_types: set[str] = set()
    for result in check.results:
      result_types.update(entry.type_url for entry in result.data)

    deps: set[tuple[str, bool|None]] = set()
    class visitor(edge.GroupVisitor):
      def visit_edge(self, edge: Edge):
        satisfied: bool|None = None
        if edge.HasField("resolution"):
          satisfied = edge.resolution.satisfied
        deps.add((from_id(edge.target), satisfied))
    visitor().visit(*check.dependencies)

    return _IndexEntrySnapshot(
        kind=check.kind,
        state=check.state,
        option_types=set(entry.type_url for entry in check.options),
        result_types=result_types,
        deps=deps,
    )


@dataclass
class FakeTurboCIOrchestrator(TurboCIClient):
  # If set, FakeTurboCIOrchestrator will use a monotonic internal clock for
  # revisions instead of time.monotonic_ns.
  test_mode: bool = field(kw_only=True)

  # This is overkill as long as recipes use a single thread for execution
  # - however this should allow this fake to be obviously correct even without
  # the GIL.
  _lock: Lock = field(default_factory=Lock)

  # Updated with `time.monotonic_ns()` on every write.
  # In test mode this is updated by incrementing the seconds field by 1 on every
  # write.
  _revision: Revision = field(default_factory=Revision)

  # Map of node id -> Check|Datum
  _db: dict[str, Check|Datum] = field(default_factory=dict)

  # secondary indices - keep synchronized with _IndexEntrySnapshot and
  # _update_indices_locked.

  # x -> ids
  _db_by_kind: defaultdict[CheckKind, set[str]] = field(
      default_factory=lambda: defaultdict(set))
  _db_by_state: defaultdict[CheckState, set[str]] = field(
      default_factory=lambda: defaultdict(set))
  _db_by_option_type: defaultdict[str, set[str]] = field(
      default_factory=lambda: defaultdict(set))
  _db_by_result_type: defaultdict[str, set[str]] = field(
      default_factory=lambda: defaultdict(set))

  # from (X, satisfied) -> checks which point at X
  #
  # If satisfied is None, it means that X isn't FINAL yet, so the incoming
  # edges are unresolved.
  # If it's True, it means that it's final and these are resolved edges which
  # are satisfied by X.
  # If it's False, it means that it's final and these are resolved edges which
  # are unsatisfied by X.
  _db_by_dependents: defaultdict[tuple[str, bool|None], set[str]] = field(
      default_factory=lambda: defaultdict(set))

  def _update_indices_locked(self, check_id: str, prev: _IndexEntrySnapshot, check: Check):
    """Updates indices based on fully validated check and _IndexEntrySnapshot.

    Must not raise exceptions, because this is called after actually applying
    the write of `check`. Raising here would leave the indexes in an
    inconsistent state vs. the data in self._db.
    """
    cur = _IndexEntrySnapshot.for_check(check)

    # Kind can only be added when the check is created.
    if prev.kind != cur.kind:
      if prev.kind is not None:
        # NOTE: This should never happen under normal circumstances; however we
        # cannot raise an exception in this function (for an assert) and we
        # would prefer to keep _db_by_kind correct.
        self._db_by_kind[prev.kind].discard(check_id)
      self._db_by_kind[cur.kind].add(check_id)

    if prev.state != cur.state:
      # prev.state can be None if the check didn't exist before.
      if prev.state is not None:
        self._db_by_state[prev.state].discard(check_id)
      self._db_by_state[cur.state].add(check_id)

    # options and result types are only addative
    for typ in cur.option_types - prev.option_types:
      self._db_by_option_type[typ].add(check_id)
    for typ in cur.result_types - prev.result_types:
      self._db_by_result_type[typ].add(check_id)

    # dependencies are fully mutable while in PLANNING, so we need to compute
    # removals and additions.
    for dep in cur.deps - prev.deps:
      self._db_by_dependents[dep].add(check_id)
    for dep in prev.deps - cur.deps:
      self._db_by_dependents[dep].discard(check_id)

    # If this write transitions this check to FINAL, we need to resolve any
    # edges in dependents which point to this check. This MAY also transition
    # the dependent check from PENDING to WAITING.
    #
    # NOTE: This duplicates logic with ResolveEdges because we only support
    # the condition `check.state == FINAL` as resolution criteria for now.
    if prev.state != CHECK_STATE_FINAL and cur.state == CHECK_STATE_FINAL:
      # We know all existing dependents entries which point at check_id have no
      # satisfied value (None). Find them all and update them.

      # to avoid modifying the indexes while we are iterating in the loop,
      # buffer all writes.
      writes: list[WriteNodesRequest.CheckWrite] = []
      for dependent_id in self._db_by_dependents[check_id, None]:
        dependent = self._db[dependent_id]
        assert isinstance(dependent, Check)

        # calculate new dependency tree for the dependent, using `check` as the
        # target node for the edges. Buffer the resulting write.
        dependencies = deepcopy(dependent.dependencies)
        fully_unblocked = edge.resolve_edges(
            *dependencies,
            at=self._revision,
            targets=[check])

        writes.append(WriteNodesRequest.CheckWrite(
            identifier=dependent.identifier,
            state=CHECK_STATE_WAITING if fully_unblocked else None,
            dependencies=dependencies,
        ))

      for write in writes:
        self._indexed_apply_locked(write)

  def _apply_locked(self, write: WriteNodesRequest.CheckWrite) -> Check:
    ident_str = from_id(write.identifier)
    check: Check

    touched = [False]
    def _touch():
      if not touched[0]:
        touched[0] = True
        check.version.CopyFrom(self._revision)

    if cur := self._db.get(ident_str):
      check = cast(Check, cur)
    else:
      check = Check(
          identifier=write.identifier,
          kind=write.kind,
          state=CHECK_STATE_PLANNING,
      )
      self._db[ident_str] = check
      _touch()

    RT = TypeVar('RT', Check.OptionRef, Check.Result.ResultDatumRef)
    def _write_data(
        to_write: RepeatedCompositeFieldContainer[WriteNodesRequest.RealmValue],
        refs: RepeatedCompositeFieldContainer[RT],
        mk_ref: Callable[[str, int], RT],
    ):
      typId: dict[str, identifier.Identifier] = {
        ref.type_url: wrap_id(ref.identifier) for ref in refs}
      for realmValue in to_write:
        type_url = realmValue.value.type_url
        if (cur_id := typId.get(type_url)) is None:
          # we're adding a new datum
          _touch()
          ref = mk_ref(type_url, len(refs)+1)
          refs.append(ref)
          cur_id = wrap_id(ref.identifier)
          typId[type_url] = cur_id

        dat = Datum(
            identifier=cur_id,
            version=self._revision,
            realm=realmValue.realm or None,
        )
        dat.value.value.CopyFrom(realmValue.value)
        self._db[from_id(cur_id)] = dat

    new_state: CheckState = write.state

    if write.dependencies:
      dependencies = deepcopy(write.dependencies)
      edge.prune_empty_groups(dependencies)

      targ_ids = edge.extract_target_ids(*dependencies, want='*')
      # NOTE: This duplicates logic with edge.ResolveEdges.
      fully_unblocked = edge.resolve_edges(
          *dependencies,
          at=self._revision,
          targets=[
            node for ident_str in targ_ids
            if (
              isinstance((node := self._db.get(ident_str)), Check) and
              node.state == CHECK_STATE_FINAL)
          ]
      )
      if fully_unblocked and (
          check.state == CHECK_STATE_PLANNED or
          new_state == CHECK_STATE_PLANNED):
        new_state = CHECK_STATE_WAITING

      _touch()
      del check.dependencies[:]
      check.dependencies.extend(dependencies)

    if new_state:
      _touch()
      check.state = new_state
      # If the user moves us to PLANNED, but we're actually already fully
      # resolved, we can move directly to WAITING.
      if check.state == CHECK_STATE_PLANNED:
        if all(
            group.resolution.satisfied
            for group in check.dependencies
        ):
          check.state = CHECK_STATE_WAITING

    if write.options:
      _write_data(
          write.options, check.options,
          lambda type_url, idx: Check.OptionRef(
              identifier=identifier.CheckOption(
                  check=write.identifier, idx=idx),
              type_url=type_url,
          ))

    finalize_results = write.finalize_results or new_state == CHECK_STATE_FINAL

    if (write.results or finalize_results) and not check.results:
      _touch()
      check.results.append(Check.Result(created_at=self._revision))

    if write.results:
      # NOTE: results[0] is because there is no way in this fake to end up with
      # multiple results for a single check. In the real system, each unique
      # stage attempt writing to a check would get a different CheckResult to
      # write into.
      _write_data(
          write.results, check.results[0].data,
          lambda type_url, idx: Check.Result.ResultDatumRef(
              identifier=identifier.CheckResultDatum(
                  result=identifier.CheckResult(check=write.identifier, idx=1),
                  idx=idx,
              ),
              type_url=type_url))

    if finalize_results:
      check.results[0].finalized_at.CopyFrom(self._revision)

    return check

  def _indexed_apply_locked(self, write: WriteNodesRequest.CheckWrite):
    ident_str = from_id(write.identifier)
    idx_snap = _IndexEntrySnapshot.for_check(
        cast(Check|None, self._db.get(ident_str)))
    check = self._apply_locked(write)
    self._update_indices_locked(
        ident_str, idx_snap, check)

  def _select_nodes_locked(self, sel: Query.Select) -> tuple[
      dict[str, identifier.Identifier],
      dict[str, identifier.Identifier],
  ]:
    """Processes a Query.Select into a set of nodes_ids."""
    ret: dict[str, identifier.Identifier] = {}
    absent: dict[str, identifier.Identifier] = {}

    # fake ignores .workplan - it only simulates a single workplan

    explicit = {from_id(ident): ident for ident in sel.nodes}
    for k, v in explicit.items():
      if k in self._db:
        ret[k] = v
      else:
        absent[k] = v

    for pattern in sel.check_patterns:
      sets: list[set[str]] = []

      if pattern.kind:
        sets.append(self._db_by_kind[pattern.kind])

      if pattern.with_option_types:
        ops_set = set()
        for typ in pattern.with_option_types:
          ops_set.update(self._db_by_option_type[typ])
        sets.append(ops_set)

      if pattern.with_result_data_types:
        result_set = set()
        for typ in pattern.with_result_data_types:
          result_set.update(self._db_by_result_type[typ])
        sets.append(result_set)

      if pattern.state:
        sets.append(self._db_by_state[pattern.state])

      if sets:
        base = set.intersection(*sets)
      else:
        base = {key for key, node in self._db.items() if isinstance(node, Check)}

      new_matches = base - ret.keys()
      if pattern.id_regex:
        pat = re.compile(r'L\d*:C'+pattern.id_regex)
        new_matches = {ident_str for ident_str in new_matches
                       if pat.match(ident_str)}
      ret.update((ident_str, to_id(ident_str)) for ident_str in new_matches)

    if sel.stage_patterns:
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `query.stage_patterns`")

    return ret, absent


  def _expand_nodes_locked(self, expand: Query.Expand, state: dict[str, identifier.Identifier]):
    if not expand.dependencies:
      return
    deps = expand.dependencies

    satisfied: bool|None = None
    if deps.HasField('satisfied'):
      satisfied = deps.satisfied

    # base_checks is the set of checks to expand. All expansions will be based
    # off this.
    base_checks: dict[str, tuple[identifier.Identifier, Check]] = {
      ident_str: (ident, cast(Check, self._db[ident_str])) for ident_str, ident in state.items()
      if ident.WhichOneof('type') == 'check'
    }

    # Walk Checks along their dependencies.
    if depth := deps.dependencies_depth:
      # This is the layer of nodes that we are about to walk down.
      tier_down: dict[str, tuple[identifier.Identifier, Check]] = base_checks
      # These are nodes that we already did walk down. We will use these
      # to prevent traversing the same node multiple times.
      walked_down: set[str] = set()
      for _ in range(depth):
        next_tier_down: dict[str, tuple[identifier.Identifier, Check]] = {}
        for key, (_, check) in tier_down.items():
          walked_down.add(key[0])
          next_tier_down.update({
            ident_str: (ident, cast(Check, self._db[ident_str]))
            for ident_str, ident in edge.extract_target_ids(
                *check.dependencies,
                satisfied=satisfied,
            ).items()
            if ident_str not in state
          })
        state.update({
          ident_str: ident for ident_str, (ident, _) in next_tier_down.items()
        })
        tier_down = {k: v for k, v in next_tier_down.items()
                     if k not in walked_down}

    # Walk dependents of Checks (i.e. walk 'backwards' from Checks to other
    # nodes which depend on it).
    if depth := deps.dependents_depth:
      # To go along dependents, we need to use a index - keeping the Check won't
      # help us.
      tier_up: set[str] = set(k for k in base_checks.keys())
      walked_up: set[str] = set()
      for _ in range(depth):
        next_tier_up: set[str] = set()
        for ident_str in tier_up:
          walked_up.add(ident_str)
          next_tier_up.update(self._db_by_dependents[ident_str, satisfied])
          if satisfied is None:
            next_tier_up.update(self._db_by_dependents[ident_str, True])
            next_tier_up.update(self._db_by_dependents[ident_str, False])
        state.update((ident_str, to_id(ident_str)) for ident_str in next_tier_up)
        tier_up = next_tier_up - walked_up


  def _collect_nodes_locked(self, graph: dict[str, Check|Datum], query: Query,
                            state: dict[str, identifier.Identifier],
                            require: Revision|None):
    """Collect adds all required nodes to the GraphView."""
    types = set(query.type_urls)
    collect = query.collect
    if collect.check.HasField('edits'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `query.collect.check.edits`")
    if collect.HasField('stage'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `query.collect.stage`")

    collect_opts = collect.check.options
    collect_result_data = collect.check.result_data

    toProcess: list[tuple[str, identifier.Identifier]] = list(state.items())
    while toProcess:
      node_str, ident = toProcess.pop()
      # Add the node directly to our graph.
      nodeVal = self._db.get(node_str, None)
      if not nodeVal:
        continue
      if require and _is_rev_newer(nodeVal.version, require):
        raise TransactionConflictException(
            f"node {node_str} newer than {require}",
            failure_message=TransactionConflictFailure())
      if node_str not in graph:
        graph[node_str] = copy.deepcopy(nodeVal)

      if ((collect_opts or collect_result_data)
          and ident.WhichOneof('type') == 'check'):
        if collect_opts:
          assert isinstance(nodeVal, Check)
          for opt in nodeVal.options:
            if opt.type_url in types:
              toProcess.append((from_id(opt.identifier), wrap_id(opt.identifier)))

        if collect_result_data:
          assert isinstance(nodeVal, Check)
          for rslt in nodeVal.results:
            for dat in rslt.data:
              if dat.type_url in types:
                toProcess.append((from_id(dat.identifier), wrap_id(dat.identifier)))


  def QueryNodes(self, req: QueryNodesRequest) -> QueryNodesResponse:
    if req.stage_attempt_token:
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `stage_attempt_token`")
    if req.version.HasField('snapshot'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `version.snapshot`")

    with self._lock:
      graph: dict[str, Check|Datum] = {}
      all_absent: dict[str, identifier.Identifier] = {}
      for query in req.query:
        state, absent = self._select_nodes_locked(query.select)
        all_absent.update(absent)
        if query.expand:
          self._expand_nodes_locked(query.expand, state)
        self._collect_nodes_locked(
            graph, query, state,
            req.version.require if req.version.HasField('require') else None)
      version = self._revision

    ret = GraphView(version=version)
    checkViews: dict[str, CheckView] = {}
    def _get(cid: str) -> CheckView:
      if not (cur := checkViews.get(cid, None)):
        cur = ret.checks.add()
        checkViews[cid] = cur
      return cur

    for ident_str, node in graph.items():
      if isinstance(node, Check):
        _get(ident_str).check.CopyFrom(node)
      else:
        assert isinstance(node, Datum)
        match node.identifier.WhichOneof('type'):
          case 'check_option':
            cv = _get(from_id(node.identifier.check_option.check))
            cv.option_data.append(node)
          case 'check_result_datum':
            rslt_id = node.identifier.check_result_datum.result
            cv = _get(from_id(rslt_id.check))
            for cur in cv.results:
              if cur.identifier.idx == rslt_id.idx:
                cur.data.append(node)
                break
            else:
              cv.results.add(data=[node])

    # make everything sorted
    ret.checks.sort(key=lambda c: (
      c.check.identifier.work_plan.id, c.check.identifier.id))
    ret.stages.sort(key=lambda s: (
      s.stage.identifier.work_plan.id, s.stage.identifier.id))
    for check in ret.checks:
      check.option_data.sort(key=lambda o: o.identifier.check_option.idx)
      check.results.sort(key=lambda r: r.identifier.idx)
      for result in check.results:
        result.data.sort(key=lambda d: d.identifier.check_result_datum.idx)

    return QueryNodesResponse(
        graph=ret,
        absent=all_absent.values(),
    )


  def WriteNodes(self, req: WriteNodesRequest) -> WriteNodesResponse:
    if req.stage_attempt_token:
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.WriteNodes: `stage_attempt_token`")

    if req.stages:
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.WriteNodes: `stages`")

    if req.HasField('current_stage'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.WriteNodes: `current_stage`")

    if not req.reasons:
      raise InvalidArgumentException(
          "WriteNodes: at least one reason is required")
    # TODO: check duplicate reason (realm, type)

    if req.HasField('txn'):
      for ident in req.txn.nodes_observed:
        match typ := ident.WhichOneof('type'):
          case 'check' | 'check_option' | 'check_result_datum':
            pass
          case _:
            raise InvalidArgumentException(
                f"WriteNodes.txn.nodes_observed: unsupported kind {typ}")
      # check that req.snapshot_version is set?

    seen_ids: set[str] = set()
    dups: set[str] = set()
    for check in req.checks:
      if check.identifier.work_plan.id:
        raise NotImplementedError(
            "FakeTurboCIOrchestrator.WriteNodes: "
            "`checks.idententifier.work_plan.id`")
      if check.realm:
        raise NotImplementedError(
            "FakeTurboCIOrchestrator.WriteNodes: "
            "`checks.realm`")
      for opt in check.options:
        if opt.realm:
          raise NotImplementedError(
              "FakeTurboCIOrchestrator.WriteNodes: "
              "`checks.options.realm`")
      for rslt in check.results:
        if rslt.realm:
          raise NotImplementedError(
              "FakeTurboCIOrchestrator.WriteNodes: "
              "`checks.results.realm`")

      ident_str = from_id(check.identifier)
      if ident_str not in seen_ids:
        seen_ids.add(ident_str)
      else:
        dups.add(ident_str)

    if dups:
      raise InvalidArgumentException(
          "WriteNodes: duplicate check writes: {dups}")

    with self._lock:
      if req.txn.nodes_observed:
        too_new: set[str] = set()
        def _observe(ident_str: str|None) -> Check|Datum|None:
          if not ident_str:
            return None
          if (cur := self._db.get(ident_str, None)) is not None:
            if _is_rev_newer(cur.version, req.txn.snapshot_version):
              too_new.add(ident_str)
            return cur

        for ident in req.txn.nodes_observed:
          _observe(from_id(ident))
        # now observe all implied nodes
        for check in req.checks:
          cur = cast(Check|None, _observe(from_id(check.identifier)))
          if cur:
            opt_typ_to_ident = {ref.type_url: from_id(ref.identifier) for ref in cur.options }
            for opt in check.options:
              _observe(opt_typ_to_ident.get(opt.value.type_url))
            # Our fake only supports one 'stage', so all results are recorded on
            # results[0].
            if cur.results:
              rslt_typ_to_ident = {ref.type_url: from_id(ref.identifier)
                                   for ref in cur.results[0].data}
              for rslt in check.results:
                _observe(rslt_typ_to_ident.get(rslt.value.type_url))

        if too_new:
          raise TransactionConflictException(
              f"WriteNodes: nodes changed since snapshot_version: {too_new}",
              failure_message=TransactionConflictFailure())

      # check that we can apply all deltas
      needed_checks: set[str] = set()
      added_checks: set[str] = set()
      for check in req.checks:
        ident_str = from_id(check.identifier)
        added_checks.add(ident_str)
        cur = self._db.get(ident_str)
        check_invariant.assert_can_apply(check, cast(Check|None, cur))
        if check.dependencies:
          needed_checks.update(edge.extract_target_ids(
              *check.dependencies, want='check'))

      missing_checks = needed_checks - added_checks
      if missing_checks:
        actually_missing = set()
        while missing_checks:
          check_id = missing_checks.pop()
          if check_id not in self._db:
            actually_missing.add(check_id)
        if actually_missing:
          raise InvalidArgumentException(
              f"unsatisfiable dependencies: {actually_missing}")

      # no exceptions past this point

      if self.test_mode:
        new_version = Revision(ts=Timestamp(seconds=self._revision.ts.seconds+1))
      else:
        now = time.monotonic_ns()
        new_version = Revision(
            ts=Timestamp(seconds=int(now // 1e9), nanos=int(now % 1e9)))
      self._revision = new_version
      for check in req.checks:
        self._indexed_apply_locked(check)

    return WriteNodesResponse(written_version=new_version)
