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

Subsets of the workplan state can be serialized as proto to be passed to another
process.

The workplan state in this process can also be bulk-updated from such a serialized
subset to allow an exported workplan subset to be returned; however this
bulk-update will be lossy since there will be no central, synchronized, process
to reconcile edits. (Once the real remote service exists, it will be able to
allow many different processes to explicitly coordinate via edits to a single
workplan. The bulk update functionality will just be to help model this in limited
contexts during the migration, e.g. when triggering one build from another).

This fake does NO security handling for the workplan data which will be present
in the real service. Functionality described by the protos, but not implemented
by this fake, will raise NotImplementedError.
"""

from __future__ import annotations

import re
import time

from collections import defaultdict
from dataclasses import dataclass, field
from functools import reduce
from itertools import chain
from threading import Lock
from typing import Callable, cast

from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from google.protobuf.timestamp_pb2 import Timestamp

from PB.turboci.graph.ids.v1 import identifier

from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_state import (CheckState,
                                                          CHECK_STATE_PLANNING,
                                                          CHECK_STATE_WAITING,
                                                          CHECK_STATE_FINAL)
from PB.turboci.graph.orchestrator.v1.dependencies import Dependencies
from PB.turboci.graph.orchestrator.v1.edge import RESOLUTION_SATISFIED
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.query_nodes_response import QueryNodesResponse
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.transaction_invariant import TransactionConflictFailure
from PB.turboci.graph.orchestrator.v1.type_set import TypeSet
from PB.turboci.graph.orchestrator.v1.value_ref import ValueRef
from PB.turboci.graph.orchestrator.v1.value_write import ValueWrite
from PB.turboci.graph.orchestrator.v1.workplan import WorkPlan
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.orchestrator.v1.write_nodes_response import WriteNodesResponse
from recipe_engine.internal.turboci import check_invariant
from recipe_engine.internal.turboci import edge
from recipe_engine.internal.turboci.common import get_check_by_full_id
from recipe_engine.internal.turboci.errors import TransactionConflictException, InvalidArgumentException

from .ids import from_id, to_id, wrap_id
from .common import TurboCIClient


def _is_rev_newer(a: Revision, b: Revision) -> bool:
  return (a.ts.seconds, a.ts.nanos) > (b.ts.seconds, b.ts.nanos)


class _all_nodes_set:
  """_all_nodes_set is a fake universal set for nodes to simplify some
  of the query logic.
  """
  def __and__(self, other):
    return other

  def __rand__(self, other):
    return other

  def __contains__(self, other):
    return True


def _type_set_to_re(ts: TypeSet) -> re.Pattern:
  fragments: list[str] = []
  for frag in ts.type_urls:
    q = re.escape(frag)
    if q.endswith(r'\*'):
      fragments.append(q.removesuffix(r'\*')+'.*')
    else:
      fragments.append(q)

  return re.compile(f'({")|(".join(fragments)})')


def _want_value_ref(type_set: TypeSet, value_ref: ValueRef) -> bool:
  pat = _type_set_to_re(type_set)
  return bool(pat.match(value_ref.type_url))


@dataclass
class _IndexEntrySnapshot:
  kind: CheckKind = CheckKind.CHECK_KIND_UNKNOWN
  state: CheckState = CheckState.CHECK_STATE_UNKNOWN
  option_types: set[str] = field(default_factory=set)
  result_types: set[str] = field(default_factory=set)

  @staticmethod
  def for_check(check: Check | None) -> _IndexEntrySnapshot:
    if check is None:
      return _IndexEntrySnapshot()

    result_types: set[str] = set()
    for result in check.results:
      result_types.update(entry.type_url for entry in result.data)

    return _IndexEntrySnapshot(
        kind=check.kind,
        state=check.state,
        option_types=set(entry.type_url for entry in check.options),
        result_types=result_types,
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

  # Map of node id -> Check
  #
  # TODO: use sortedcontainers instead of a dict?
  _checks: dict[str, Check] = field(default_factory=dict)

  def _get_check(self, ident_str: str) -> Check | None:
    # TODO: This function can be removed once _checks is split into per-type tables
    # (it would just be `self._checks.get`.
    node = self._checks.get(ident_str)
    if isinstance(node, Check):
      return node
    return None

  def _must_get_check(self, ident_str: str) -> Check:
    # TODO: This function can be removed once _checks is split into per-type tables
    # (it would just be `self._checks.get`.
    node = self._checks.get(ident_str)
    if isinstance(node, Check):
      return node
    if node is None:
      raise AssertionError(
          f'_must_get_check did not find check {ident_str!r}.')
    raise AssertionError(
        f'_must_get_check found non-check {node!r}.')

  # secondary indices - keep synchronized with _IndexEntrySnapshot and
  # _update_indices_locked.

  # x -> ids
  _checks_by_kind: defaultdict[CheckKind, set[str]] = field(
      default_factory=lambda: defaultdict(set))
  _checks_by_state: defaultdict[CheckState, set[str]] = field(
      default_factory=lambda: defaultdict(set))
  _checks_by_opt_type: defaultdict[str, set[str]] = field(
      default_factory=lambda: defaultdict(set))
  _checks_by_result_type: defaultdict[str, set[str]] = field(
      default_factory=lambda: defaultdict(set))

  _dependencies: edge.DependencyIndex = field(
      default_factory=edge.DependencyIndex)

  def _advance_revision_locked(self) -> Revision:
    """Advances the database revision to the next logical version.

    Under test mode this advances self._revision.seconds by 1.

    Otherwise, populates self._revision with the current actual timestamp
    according to time.monotonic_ns(). This can happen when running recipes in
    contexts where TurboCI is not enabled, or there is no access token for it in
    LUCI_CONTEXT. Using monotonic_ns will allow data dumped from these to at
    least have timestamps which are mostly consistent with wall clock times in
    most cases to help with debugging. Ideally we just get to the point where
    the real APIs are available all the time in non-testing scenarios.
    """
    if self.test_mode:
      new_version = Revision(
          ts=Timestamp(seconds=self._revision.ts.seconds + 1))
    else:
      now = time.monotonic_ns()
      new_version = Revision(
          ts=Timestamp(seconds=int(now // 1e9), nanos=int(now % 1e9)))
    self._revision = new_version
    return new_version

  def _update_indices_locked(self, check_id: str, prev: _IndexEntrySnapshot, check: Check):
    """Updates indices based on fully validated check and _IndexEntrySnapshot.

    Must not raise exceptions, because this is called after actually applying
    the write of `check`. Raising here would leave the indexes in an
    inconsistent state vs. the data in self._checks.
    """
    cur = _IndexEntrySnapshot.for_check(check)

    # Kind can only be added when the check is created.
    if prev.kind != cur.kind:
      if prev.kind is not None:
        # NOTE: This should never happen under normal circumstances; however we
        # cannot raise an exception in this function (for an assert) and we
        # would prefer to keep _checks_by_kind correct.
        self._checks_by_kind[prev.kind].discard(check_id)
      self._checks_by_kind[cur.kind].add(check_id)

    if prev.state != cur.state:
      # prev.state can be None if the check didn't exist before.
      if prev.state is not None:
        self._checks_by_state[prev.state].discard(check_id)
      self._checks_by_state[cur.state].add(check_id)

    # options and result types are only additive
    for typ in cur.option_types - prev.option_types:
      self._checks_by_opt_type[typ].add(check_id)
    for typ in cur.result_types - prev.result_types:
      self._checks_by_result_type[typ].add(check_id)


  def _set_check_state(self, check: Check, state: CheckState):
    if check.state == state:
      return
    check.state = state
    check.state_history.add(state=state, version=self._revision)


  def _apply_checkwrite_locked(self, write: WriteNodesRequest.CheckWrite,
                               deps: Dependencies | None) -> Check:
    """Applies a raw CheckWrite, plus the corresponding pre-normalized
    Dependencies (if any).

    NOTE: This function should never consider write.dependencies in any
    capacity.
    """
    ident_str = from_id(write.identifier)
    check: Check

    touched = [False]

    def _touch():
      if not touched[0]:
        touched[0] = True
        check.version.CopyFrom(self._revision)

    if cur := self._checks.get(ident_str):
      check = cast(Check, cur)
    else:
      check = Check(
          identifier=write.identifier,
          kind=write.kind,
      )
      self._set_check_state(check, CHECK_STATE_PLANNING)
      # New check without deps creates empty dependencies.
      #
      # This is important to trigger the check for resolving empty deps in the
      # PLANNED state.
      if deps is None:
        deps = Dependencies()
      self._checks[ident_str] = check
      _touch()

    def _write_values(
        to_write: RepeatedCompositeFieldContainer[ValueWrite],
        container: RepeatedCompositeFieldContainer[ValueRef],
    ):
      type_url_set: set[str] = {
          value_ref.type_url for value_ref in container
      }
      # TODO: Assert that realm does not mutate, and for newly created data
      # without a specified realm, mirror the check's realm.
      for value_write in to_write:
        type_url = value_write.data.type_url
        if type_url in type_url_set:
          # updating existing ValueRef
          # find it in container
          for vr in container:
            if vr.type_url == type_url:
              value_ref = vr
              break
          else:
            # Should be unreachable if type_url_set logic is correct
            raise AssertionError("ValueWrite not found in container")
        else:
          # we're adding a new ValueRef
          # add to check container
          value_ref = container.add()
          type_url_set.add(type_url)

        # Update ValueRef fields
        if value_write.realm:
          value_ref.realm = value_write.realm
        value_ref.type_url = type_url
        value_ref.inline.binary.CopyFrom(value_write.data)

        # Update the check's version
        _touch()

    if write.options:
      _write_values(write.options, check.options)

    finalize_results = write.finalize_results or write.state == CHECK_STATE_FINAL

    if (write.results or finalize_results) and not check.results:
      _touch()
      check.results.append(Check.Result(created_at=self._revision))

    if write.results:
      # NOTE: results[0] is because there is no way in this fake to end up with
      # multiple results for a single check. In the real system, each unique
      # stage attempt writing to a check would get a different CheckResult to
      # write into.
      _write_values(write.results, check.results[0].data)

    if finalize_results:
      check.results[0].finalized_at.CopyFrom(self._revision)

    was_planning = check.state == CheckState.CHECK_STATE_PLANNING
    now_planning = was_planning
    if write.HasField('state'):
      _touch()
      self._set_check_state(check, write.state)
      now_planning = write.state == CheckState.CHECK_STATE_PLANNING

    ##### All dependencies related code is below ###############################

    # deps_newly_resolved indicates if this write action caused the dependencies
    # to be resolved.
    deps_newly_resolved = False

    wrote_deps = deps is not None
    if wrote_deps:
      _touch()
      check.dependencies.CopyFrom(deps)
      # We just changed deps - check if the caller passed in already resolved
      # deps (i.e. as the result of self._dependencies.process_queue).
      deps_newly_resolved = deps.HasField('resolution')

    # We need to index_predicate as long as we updated deps during PLANNING
    # (i.e. user changed the predicate/edges), OR when we first transition from
    # PLANNING to not-PLANNING (i.e. we need to mark the predicate as immutable
    # and start receiving resolution_events).
    if ((wrote_deps and now_planning) or (was_planning and not now_planning)):
      # If we're no longer PLANNING, we need to mark the predicate as immutable.
      last_index_predicate = not now_planning

      self._dependencies.index_predicate(
          ident_str,
          check.dependencies,
          self._revision,
          mark_immutable=last_index_predicate)

      if last_index_predicate:
        # NOTE: When we mark the predicate as immutable, it will populate
        # resolution_events with any already-resolved conditions. This may be
        # enough to immediately resolve the dependencies.
        deps_newly_resolved = check.dependencies.HasField('resolution')

    if deps_newly_resolved:
      self._dependencies.index_resolved(ident_str, check.dependencies)

      # Note: check.state COULD already be FINAL if the user knew in advance
      # that there were no dependencies, and did a direct write to the FINAL
      # state. Only advance the state if we're still in PLANNED.
      if check.state == CheckState.CHECK_STATE_PLANNED:
        if check.dependencies.resolution == RESOLUTION_SATISFIED:
          self._set_check_state(check, CHECK_STATE_WAITING)

        else:  # unsatisfiable
          # _touch()
          # self._set_check_state(check, CheckState.CHECK_STATE_FINAL)
          #
          # At this point we would add some TBD type as a result as well
          # - however this is not yet defined, so just raise an error for
          # now.
          raise NotImplementedError(
              f'FakeTurboCIOrchestrator: unsatisfiable dependencies')

    # Finally, see if we can unblock any other nodes.
    #
    # This must be the very last operation in this function, because it's
    # allowed to observe any immutable data about `check`. If we put this higher
    # up in the function, it's possible that we would miss changes to
    # check.dependencies and/or check.state.
    self._dependencies.index_node_write(check)

    return check

  def _index_apply_checkwrite_locked(self, write: WriteNodesRequest.CheckWrite,
                                     deps: Dependencies | None):
    """Apply a check write and its normalized dependencies, ensuring that the indexes
    reflect this write."""
    ident_str = from_id(write.identifier)
    idx_snap = _IndexEntrySnapshot.for_check(
        cast(Check | None, self._checks.get(ident_str)))
    check = self._apply_checkwrite_locked(write, deps)
    self._update_indices_locked(ident_str, idx_snap, check)

  def _ensure_check_in_workplan(self, workplan: WorkPlan,
                                check_str: str) -> Check | tuple[None, None]:
    check = self._checks.get(check_str)
    if check is None:
      return None, None

    ret = get_check_by_full_id(workplan, check_str)
    if not ret:
      ret = workplan.checks.add()
      ret.CopyFrom(check)

      for opt in ret.options:
        opt.inline.binary.ClearField('value')

      for rslt in ret.results:
        for dat in rslt.data:
          dat.inline.binary.ClearField('value')

    return ret


  def _select_checks_locked(self, basis: set[str]|_all_nodes_set, sel: Query.SelectChecks|None) -> set[str]:
    if not sel:
      return set()

    if not sel.predicates:
      if isinstance(basis, _all_nodes_set):
        return set(self._checks)
      return basis

    ret: set[str] = set()

    for p in sel.predicates:
      toIntersect: list[set[str]] = []

      if k := p.kind:
        toIntersect.append(self._checks_by_kind[k] & basis)

      if st := p.state:
        toIntersect.append(self._checks_by_state[st] & basis)

      if ot := p.with_option_type:
        pat = _type_set_to_re(ot)
        for type_url, node_ids in self._checks_by_opt_type.items():
          if pat.match(type_url):
            toIntersect.append(node_ids & basis)

      if rdt := p.with_result_data_type:
        pat = _type_set_to_re(rdt)
        for type_url, node_ids in self._checks_by_result_type.items():
          if pat.match(type_url):
            toIntersect.append(node_ids & basis)

      ret.update(reduce(lambda a, b: a&b, toIntersect))

    return ret


  def _select_nodes_locked(
      self, workplan: WorkPlan, q: Query) -> tuple[
          set[str],
          dict[str, identifier.Identifier],
      ]:
    """Processes a Query.Select into a set of nodes_ids."""
    absent: dict[str, identifier.Identifier] = {}
    basis: _all_nodes_set | set[str]

    match ns := q.WhichOneof('node_set'):
      case 'nodes_by_id':
        basis = set()

        implied_select_checks = False
        # implied_select_stages = False

        for ident in q.nodes_by_id.nodes:
          match typ := ident.WhichOneof('type'):
            case 'check':
              implied_select_checks = True
              ident_str = from_id(ident)
              if ident_str in self._checks:
                basis.add(ident_str)
              else:
                absent[ident_str] = ident

            case _:
              raise NotImplementedError(
                  "FakeTurboCIOrchestrator.QueryNodes: "
                  f"`query.nodes_by_id` has unsupported type {typ!r}")

        if implied_select_checks and not q.HasField('select_checks'):
          q.select_checks.SetInParent()

      case 'nodes_in_workplan':
        if id := q.nodes_in_workplan.id:
          raise NotImplementedError(
            f"FakeTurboCIOrchestrator.QueryNodes: nodes_in_workplan with non-empty id {id!r}")

        basis = _all_nodes_set()

      case _:
        raise NotImplementedError(
            f"FakeTurboCIOrchestrator.QueryNodes: `query.{ns}`")

    if q.HasField('select_stages'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `query.select_stages`")

    selected = self._select_checks_locked(basis, q.select_checks)
    for node_id in selected:
      self._ensure_check_in_workplan(workplan, node_id)

    return selected, absent


  def _expand_nodes_locked(self, workplan: WorkPlan, q: Query,
                           toCollect: set[str]):
    """Expands the nodes in `toCollect` according to `q`.

    This entails walking 'forwards' and 'backwards' through the workplan along
    dependency edges.
    """
    # Need separate set to avoid changing toCollect while iterating on it.
    to_add: set[str] = set()

    if q.HasField('expand_dependencies'):
      for node_ident_str in toCollect:
        matches = self._dependencies.dependencies_of(
            node_ident_str, q.expand_dependencies.mode)
        for match in matches:
          self._ensure_check_in_workplan(workplan, match)
        to_add.update(matches)

    if q.HasField('expand_dependents'):
      for node_ident_str in toCollect:
        matches = self._dependencies.dependents_of(
            node_ident_str, q.expand_dependents.mode)
        for match in matches:
          self._ensure_check_in_workplan(workplan, match)
        to_add.update(matches)

    toCollect.update(to_add)

  def _collect_nodes_locked(self, workplan: WorkPlan, query: Query,
                            type_info: QueryNodesRequest.TypeInfo,
                            toCollect: set[str], require: Revision | None):
    """Collect adds all required nodes to the WorkPlan."""
    if query.collect_checks.HasField('edits'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `query.collect_checks.edits`")
    if query.HasField('collect_stages'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `query.collect_stages`")

    collect_opts = query.collect_checks.options
    collect_result_data = query.collect_checks.result_data

    for check_str in toCollect:
      check = self._checks[check_str]

      if require and _is_rev_newer(check.version, require):
        raise TransactionConflictException(
            f"node {check_str} newer than {require}",
            failure_message=TransactionConflictFailure())

      # This must already be in workplan
      workplan_check = get_check_by_full_id(workplan, check_str)

      if collect_opts:
        for i, opt in enumerate(check.options):
          if _want_value_ref(type_info.wanted, opt):
            workplan_check.options[i].CopyFrom(opt)

      if collect_result_data:
        for result_idx, result in enumerate(check.results):
          for data_idx, dat in enumerate(result.data):
            if _want_value_ref(type_info.wanted, dat):
              workplan_check.results[result_idx].data[data_idx].CopyFrom(dat)


  def QueryNodes(self, req: QueryNodesRequest) -> QueryNodesResponse:
    if req.token:
      raise NotImplementedError("FakeTurboCIOrchestrator.QueryNodes: `token`")
    if req.version.HasField('snapshot'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `version.snapshot`")
    if req.type_info.HasField('unknown_jsonpb'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `type_info.unknown_jsonpb`")
    if req.type_info.HasField('known'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.QueryNodes: `type_info.known`")

    with self._lock:
      ret = WorkPlan(
          version=self._revision, identifier=identifier.WorkPlan(id=""))
      all_absent: dict[str, identifier.Identifier] = {}
      for query in req.query:
        toCollect, absent = self._select_nodes_locked(ret, query)
        all_absent.update(absent)
        self._expand_nodes_locked(ret, query, toCollect)
        self._collect_nodes_locked(
            ret, query, req.type_info, toCollect,
            req.version.require if req.version.HasField('require') else None)

    return QueryNodesResponse(
        workplans=[ret],
        absent=all_absent.values(),
        version=self._revision,
    )

  def WriteNodes(self, req: WriteNodesRequest) -> WriteNodesResponse:
    if req.token:
      raise NotImplementedError("FakeTurboCIOrchestrator.WriteNodes: `token`")

    if req.stages:
      raise NotImplementedError("FakeTurboCIOrchestrator.WriteNodes: `stages`")

    # Handle current_attempt (allow it, but ignore content for now as we don't strictly simulate attempts)
    if req.HasField('current_stage'):
      raise NotImplementedError(
          "FakeTurboCIOrchestrator.WriteNodes: `current_stage`")

    if not req.reason:
      raise InvalidArgumentException(
          "WriteNodes: at least one reason is required")
    # TODO: check duplicate reason (realm, type)

    if req.HasField('txn'):
      for ident in req.txn.nodes_observed:
        match typ := ident.WhichOneof('type'):
          case 'check' | 'check_option':
            pass
          case _:
            raise InvalidArgumentException(
                f"WriteNodes.txn.nodes_observed: unsupported kind {typ}")
      # check that req.snapshot_version is set?

    seen_ids: set[str] = set()
    dups: set[str] = set()
    check_deps: list[None | Dependencies] = []
    for cwrite in req.checks:
      if cwrite.identifier.work_plan.id:
        raise NotImplementedError("FakeTurboCIOrchestrator.WriteNodes: "
                                  "`checks.idententifier.work_plan.id`")
      if cwrite.realm:
        raise NotImplementedError("FakeTurboCIOrchestrator.WriteNodes: "
                                  "`checks.realm`")
      for opt in cwrite.options:
        if opt.realm:
          raise NotImplementedError("FakeTurboCIOrchestrator.WriteNodes: "
                                    "`checks.options.realm`")
      for rslt in cwrite.results:
        if rslt.realm:
          raise NotImplementedError("FakeTurboCIOrchestrator.WriteNodes: "
                                    "`checks.results.realm`")

      if cwrite.HasField('dependencies'):
        check_deps.append(edge.extract_dependencies(cwrite.dependencies))
      else:
        check_deps.append(None)

      ident_str = from_id(cwrite.identifier)
      if ident_str not in seen_ids:
        seen_ids.add(ident_str)
      else:
        dups.add(ident_str)

    if dups:
      raise InvalidArgumentException(
          "WriteNodes: duplicate check writes: {dups}")

    with self._lock:
      # Note: in the real implementation this can be done in separate, parallel,
      # transactions before the main transaction.
      self._dependencies.ensure_conditions(
          chain(*(deps.edges for deps in check_deps if deps is not None)),
          self._get_check)

      if req.txn.nodes_observed:
        too_new: set[str] = set()

        def _observe(ident_str: str | None) -> Check | ValueWrite | None:
          if not ident_str:
            return None
          if (cur := self._checks.get(ident_str, None)) is not None:
            if _is_rev_newer(cur.version, req.txn.snapshot_version):
              too_new.add(ident_str)
            return cur

        for ident in req.txn.nodes_observed:
          _observe(from_id(ident))
        # now observe all implied nodes
        for cwrite in req.checks:
          _observe(from_id(cwrite.identifier))

        if too_new:
          raise TransactionConflictException(
              f"WriteNodes: nodes changed since snapshot_version: {too_new}",
              failure_message=TransactionConflictFailure())

      # check that we can apply all deltas
      needed_checks: set[str] = set()
      added_checks: set[str] = set()
      for cwrite, deps in zip(req.checks, check_deps):
        ident_str = from_id(cwrite.identifier)
        added_checks.add(ident_str)
        cur = self._checks.get(ident_str)
        check_invariant.assert_can_apply(cwrite, cast(Check | None, cur))
        if deps:
          needed_checks.update(
              from_id(e.check.identifier)
              for e in deps.edges
              if e.WhichOneof('target') == 'check')

      missing_checks = needed_checks - added_checks
      if missing_checks:
        actually_missing = set()
        while missing_checks:
          check_id = missing_checks.pop()
          if check_id not in self._checks:
            actually_missing.add(check_id)
        if actually_missing:
          raise InvalidArgumentException(
              f"unsatisfiable dependencies: {actually_missing}")

      # no exceptions past this point
      new_version = self._advance_revision_locked()
      for cwrite, deps in zip(req.checks, check_deps):
        self._index_apply_checkwrite_locked(cwrite, deps)

      # Do this until there are no more edge propagations.
      #
      # In the real implementation, these would all be asynchronous background
      # transactions on the workplan state.
      while self._dependencies.has_events():
        self._advance_revision_locked()
        to_write = self._dependencies.process_queue(
            self._must_get_check, self._revision)
        for node_ident_str, deps in to_write.items():
          node = self._checks[node_ident_str]
          if isinstance(node, Check):
            cwrite = WriteNodesRequest.CheckWrite(identifier=node.identifier)
            self._index_apply_checkwrite_locked(cwrite, deps)
          else:
            raise NotImplementedError(
                'FakeTurboCIOrchestrator: cannot resolve edges for node of'
                f' type {type(node).__name__}')

    return WriteNodesResponse(written_version=new_version)
