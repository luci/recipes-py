# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import enum
from typing import Any, Callable, Iterable, Literal, cast

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.dependencies import Dependencies
from PB.turboci.graph.orchestrator.v1.query import QueryExpandDepsMode
from PB.turboci.graph.orchestrator.v1.stage import Stage
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.edge import (
  Edge, Resolution, RESOLUTION_UNKNOWN, RESOLUTION_SATISFIED,
  RESOLUTION_UNSATISFIED)
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.stage_state import StageState
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from recipe_engine.internal.turboci.errors import InvalidArgumentException

from .ids import from_id, to_id

@dataclass(slots=True, frozen=True)
class CheckCondition:
  """Frozen version of Edge.Check.Condition."""
  on_state: CheckState
  expression: str

  @classmethod
  def from_edge(cls, check_edge: Edge.Check) -> CheckCondition:
    return cls(
        check_edge.condition.on_state or CheckState.CHECK_STATE_FINAL,
        check_edge.condition.expression or "true",
    )

  def evaluate(self, check: Check) -> Resolution:
    assert isinstance(check, Check)

    if check.state < self.on_state:
      return RESOLUTION_UNKNOWN

    if self.expression == 'true':
      return RESOLUTION_SATISFIED

    raise NotImplementedError('StageState.expression not implemented.')


@dataclass(slots=True, frozen=True)
class StageCondition:
  """Frozen version of Edge.Stage.Condition."""
  on_state: StageState
  expression: str

  @classmethod
  def from_edge(cls, stage_edge: Edge.Stage) -> StageCondition:
    return cls(
        stage_edge.condition.on_state or StageState.STAGE_STATE_FINAL,
        stage_edge.condition.expression or "true",
    )

  def evaluate(self, stage: Stage) -> Resolution:
    assert isinstance(stage, Stage)

    if stage.state < self.on_state:
      return RESOLUTION_UNKNOWN

    if self.expression == 'true':
      return RESOLUTION_SATISFIED

    raise NotImplementedError('StageState.expression not implemented.')


Condition = StageCondition | CheckCondition


def extract_ident_condition(e: Edge) -> tuple[str, Condition]:
  """Extracts the string identifier and condition for this Edge."""
  match target := e.WhichOneof('target'):
    case 'check':
      return from_id(e.check.identifier), CheckCondition.from_edge(e.check)
    case 'stage':
      return from_id(e.stage.identifier), StageCondition.from_edge(e.stage)
    case _:
      raise AssertionError(f'impossible: edge.target is {target!r}')


def extract_dependencies(
    deps: WriteNodesRequest.DependencyGroup,
    *,
    for_node_type: Literal['check', 'stage'] = 'check',
) -> Dependencies:
  """Extracts a Dependencies value from a WriteNodesRequest.DependencyGroup.

  The DependencyGroup will be checked for well-formed-ness (no empty
  groups, sensible threshold values). Raises InvalidArgumentException if there
  are issues.

  Returns the normalized Dependencies if everything looks good.
  """
  out = Dependencies()

  if for_node_type == 'check':
    allowed_targets = frozenset(('check',))
  else:  # stage
    allowed_targets = frozenset(('check', 'stage'))

  # mapping of stringified edge to index in edge table.
  edge_map: dict[tuple[str, Condition], int] = {}

  def _add_edge(e: Edge) -> int:
    if (target := e.WhichOneof('target')) not in allowed_targets:
      raise InvalidArgumentException(
          f'{for_node_type} cannot depend on objects type {target!r}.')

    key = extract_ident_condition(e)
    if (cur := edge_map.get(key)) is not None:
      return cur

    ret = len(out.edges)
    out.edges.append(e)
    edge_map[key] = ret
    return ret

  def _visit(
      group: WriteNodesRequest.DependencyGroup) -> Dependencies.Group:
    N = len(group.groups) + len(group.edges)
    threshold: int = group.threshold
    if threshold > N:
      raise InvalidArgumentException(
          f'group threshold {threshold} exceeds number '
          f'of edges+groups {N}')
    elif threshold == N:
      threshold = 0
    elif threshold < 0:
      raise InvalidArgumentException(
          f'group threshold {threshold} is less than 0')

    subgroups: list[Dependencies.Group] = []
    edges: list[int] = []

    for subgroup in group.groups:
      if len(subgroup.groups) == 0 and len(subgroup.edges) == 0:
        raise InvalidArgumentException(
            'subgroups of DependencyGroup may not be empty')
      subgroups.append(_visit(subgroup))
    for e in group.edges:
      edges.append(_add_edge(e))

    # if this group looks like:
    #   group(group=[G])
    #
    # just return G
    if len(subgroups) == 1 and len(edges) == 0:
      return subgroups[0]

    return Dependencies.Group(
        groups=subgroups,
        edges=sorted(edges),
        threshold=threshold or None,  # normalized to unset
    )

  out.predicate.CopyFrom(_visit(deps))

  return out


def resolve_dependencies(deps: Dependencies):
  """Evaluates `deps` to see if it can be resolved, based on its contained
  resolution_events.

  If it can be resolved, `statisfied` or `unsatisfiable` will be set. Otherwise
  this function will not change `deps`.
  """
  # See if we can satisfy the dependencies.
  if not deps.predicate.groups and not deps.predicate.edges:
    # empty deps are immediately resolved - set satisfied to an empty Group.
    deps.resolution = RESOLUTION_SATISFIED
    return

  def _resolve(pred: Dependencies.Group) -> Resolution:
    """If `pred` is fully resolved in `deps`, return the minimal Group which
    is the resolving subset of `pred`, or 'unsatisfiable' if this Group
    cannot ever be satisfied.

    If `pred` can not be resolved, return None.
    """
    total = len(pred.groups) + len(pred.edges)
    threshold = pred.threshold or total

    num_unsatisfied = 0
    num_satisfied = 0
    for edge in pred.edges:
      # need to do this to avoid populating deps.resolution_events :/
      # silly python...
      if edge not in deps.resolution_events:
        continue
      match deps.resolution_events[edge].resolution:
        case Resolution.RESOLUTION_SATISFIED:
          num_satisfied += 1
        case Resolution.RESOLUTION_UNSATISFIED:
          num_unsatisfied += 1

    for group in pred.groups:
      match _resolve(group):
        case Resolution.RESOLUTION_SATISFIED:
          num_satisfied += 1
        case Resolution.RESOLUTION_UNSATISFIED:
          num_unsatisfied += 1

    if total - num_unsatisfied < threshold:
      return RESOLUTION_UNSATISFIED

    if num_satisfied < threshold:
      return RESOLUTION_UNKNOWN

    return RESOLUTION_SATISFIED

  if (resolution := _resolve(deps.predicate)) != RESOLUTION_UNKNOWN:
    deps.resolution = resolution


class _DepsState(enum.Enum):
  """Small enum for the state of DependencyIndex._Entry."""

  # The dependency predicate may still be mutated.
  MUTABLE = 0

  # The dependency predicate is immutable, and this node is collecting
  # resolution_events.
  RECEIVING_EVENTS = 1

  # The dependency is fully immutable and is no longer collecting
  # resolution_events.
  RESOLVED = 2


@dataclass(slots=True)
class DependencyIndex:
  """An index of dependency edges between nodes in a TurboCI graph.

  The intended lifecycle is:
    * `ensure_conditions` before writing any dependencies.
    * `index_predicate` any time a node's dependencies.{predicate,edges} changes.
    * `index_resolved` any time a node's dependencies.resolution becomes set.
    * `index_node_write` any time a node is written (after all mutations to the
    node).
    * `process_queue` after committing a node write.

  The `index_*` methods do not need to observe the state of the graph, apart
  from the provided arguments and the current state of the *index*.

  `ensure_conditions` and `process_queue` both need to potentially observe target
  nodes in the graph.

  `dependencies_of` and `dependents_of` are read-only operations which reflect
  the current dependencies/dependents of the nodes in the graph.
  """

  @dataclass(slots=True)
  class _Entry:
    # edges_flat is a flattened easy-to-diff version of `Dependencies.edges` which
    # just includes the target ids.
    edges_flat: set[str] = field(default_factory=set)

    # satisfied_edges_flat is a flattened version of `Dependencies.satisfied` once
    # the node dependencies are RESOLVED.
    #
    # If the Dependencies are unsatisfiable, this will be empty.
    satisfied_edges_flat: set[str] = field(default_factory=set)

    # The state of the dependencies on this node.
    #
    # Progresses linearly from EDGES_MUTABLE to RESOLVED.
    #
    #   * EDGES_MUTABLE - `index_predicate` can mutate the keys in
    #   `edges_flat`.
    #   * RECEIVING_EVENTS - event propagation will update the associated node's
    #   dependencies.resolution_events.
    #   * RESOLVED - satisfied_edges_flat has been set to indicate which
    #   edges are in this node's satisfied resolution set.
    state: _DepsState = _DepsState.MUTABLE

    # Below are are secondary indices not covered by `state`. These are updated
    # by changes on OTHER nodes, and so are always mutable.

    # A map of the currently evaluated conditions for this node.
    #
    # Entries are added here when other nodes depend on this one via
    # ensure_conditions.
    #
    # Append-only via ensure_conditions.
    conditions: dict[Condition, Resolution] = field(
        default_factory=lambda: defaultdict(lambda: RESOLUTION_UNKNOWN))

    # The set of other nodes which depend on this one via edges_flat.
    #
    # Updated as part of index_predicate.
    #
    # This is always mutable (because a new Check could be added at any time in
    # the PLANNING state).
    dependents: set[str] = field(default_factory=set)

    # The set of other nodes which depend on this one via satisfied_edges_flat.
    #
    # Updated as part of index_resolved.
    #
    # This is always mutable (because a new Check could be added at any time in
    # the WAITING state).
    satisfied_dependents: set[str] = field(default_factory=set)

  # Mapping of node string identifier to an _Entry.
  _data: dict[str, _Entry] = field(
      default_factory=lambda: defaultdict(DependencyIndex._Entry))

  @dataclass(slots=True, frozen=True)
  class _ResolutionEvent:
    node_ident_str: str
    condition: Condition
    resolution: Resolution

  # Contains unprocessed resolution events.
  #
  # All dependents of these events need to incorporate them into their
  # `dependencies.resolution_events`.
  _resolution_events: set[_ResolutionEvent] = field(default_factory=set)

  def ensure_conditions(self, edges: Iterable[Edge],
                        get_node: Callable[[str], Check | Stage | None]):
    """Updates the index to ensure that the conditions in `edges` is tracked by
    the index.

    Most of the time this will be a read-only operation on the index, but if an
    edge has never been observed before, this will use `get_node` to evaluate
    the condition in that edge and store it (possibly unresolved) in the index.

    `get_node` should return the current committed state of the node, and may
    return None if the target node has not yet been written; This could happen
    when a write is creating new nodes and also edges to them. When the node is
    actually comitted, it will pick up this conditions and evaluate it as part of
    that write transaction.

    Called prior to the main transaction which would write a node containing
    `edges`.
    """
    for edge in edges:
      target_ident_str, condition = extract_ident_condition(edge)
      entry = self._data[target_ident_str]
      if condition not in entry.conditions:
        if (node := get_node(target_ident_str)) is not None:
          # CheckCondition.evaluate and StageCondition.evaluate assert their
          # argument type.
          entry.conditions[condition] = condition.evaluate(cast(Any, node))
        else:
          entry.conditions[condition] = RESOLUTION_UNKNOWN


  def index_predicate(
      self,
      node_ident_str: str,
      deps: Dependencies,
      now: Revision,
      *,
      mark_immutable: bool,
  ):
    """Updates the index to record a likely-just-mutated `deps.edges` into
    `edges_flat`.

    Raises an exception if the node dependencies are not still MUTABLE.

    If `mark_immutable` is True, advances the node dependencies state to
    RECEIVING_EVENTS (after which you should not call index_predicate again).
    """
    node = self._data[node_ident_str]

    if (state := node.state) != _DepsState.MUTABLE:
      raise ValueError(f'index_predicate[{node_ident_str!r}]: '
                       f'dependencies state {state.name}.')

    new_edges_flat = {extract_ident_condition(e)[0] for e in deps.edges}
    for to_remove in node.edges_flat - new_edges_flat:
      self._data[to_remove].dependents.discard(node_ident_str)
    for to_add in new_edges_flat - node.edges_flat:
      self._data[to_add].dependents.add(node_ident_str)
    node.edges_flat = new_edges_flat

    if mark_immutable:
      if deps.resolution_events:
        raise ValueError(
            f'index_predicate({mark_immutable=}): called with non-empty '
            'resolution_events?')

      node.state = _DepsState.RECEIVING_EVENTS

      for idx, edge in enumerate(deps.edges):
        target_ident_str, condition = extract_ident_condition(edge)
        resolution = self._data[target_ident_str].conditions[condition]
        if resolution != RESOLUTION_UNKNOWN:
          deps.resolution_events[idx].resolution = resolution
          deps.resolution_events[idx].version.CopyFrom(now)

      resolve_dependencies(deps)
      # We will set the state to RESOLVED in index_resolved

  def index_node_write(self, real_node: Check | Stage):
    """Updates the indexed conditions for `real_node`.

    Looks at current unresolved conditions for `real_node` and attempts to resolve
    them. If one or more conditions are resolved, adds events to the
    _resolution_events queue.
    """
    node_ident_str = from_id(real_node.identifier)
    node = self._data[node_ident_str]

    for condition, resolution in node.conditions.items():
      if resolution == RESOLUTION_UNKNOWN:
        new_resolution = condition.evaluate(cast(Any, real_node))
        if new_resolution != RESOLUTION_UNKNOWN:
          self._resolution_events.add(
              self._ResolutionEvent(
                  node_ident_str,
                  condition,
                  new_resolution,
              ))
          node.conditions[condition] = new_resolution

  def has_events(self) -> bool:
    """Returns True iff this DependencyIndex has a non-empty message queue."""
    return bool(self._resolution_events)

  def process_queue(self, get_node: Callable[[str], Check | Stage],
                    now: Revision) -> dict[str, Dependencies]:
    """Called after a write transaction closes.

    Propagates all pending _resolution_events into a set of pending dependency
    write operations, which must be applied by the caller.

    This diverges from the real implementation by 'instantaneously' resolving
    all events in the queue (vs. potentially doing these in parallel and/or
    asynchronous transactions in the background).

    The intent is to call this in a loop as long as has_events() returns True.
    In the real system this will happen asynchronously and/or opportunistically
    in the write handler.

    Returns a dict mapping from node identifier to Dependencies to write to that
    node. The write should include calling `index_resolved` (if appropriate),
    advancing the state of the node (if the dependencies are resolved), and
    finally `index_node_write`.
    """
    ret: dict[str, Dependencies] = {}

    for event in self._resolution_events:
      for dependent in self._data[event.node_ident_str].dependents:
        node = self._data[dependent]
        if node.state != _DepsState.RECEIVING_EVENTS:
          continue

        deps = ret.get(dependent)
        if deps is None:
          real_node = get_node(dependent)
          deps = deepcopy(real_node.dependencies)
          ret[dependent] = deps

        propagated = False
        for idx, edge in enumerate(deps.edges):
          target_ident_str, condition = extract_ident_condition(edge)
          if target_ident_str != event.node_ident_str:
            continue
          if condition != event.condition:
            continue

          if idx in deps.resolution_events:
            event = deps.resolution_events[idx]
            raise AssertionError(
                f'node[{dependent}]: already has resolution for {idx}? {event}')

          deps.resolution_events[idx].resolution = event.resolution
          deps.resolution_events[idx].version.CopyFrom(now)
          propagated = True
          break
        if not propagated:
          raise AssertionError(f'node[{dependent}]: failed to propagate {event}?')

        resolve_dependencies(deps)

    # Clear the queue.
    self._resolution_events = set()

    return ret

  def index_resolved(self, node_ident_str: str, deps: Dependencies):
    """Records that `node_ident_str` dependencies are resolved.

    `deps` must be resolved, or this raises an error.

    Must be called exactly once when this node's dependencies are resolved.
    """
    if not deps.HasField('resolution'):
      raise AssertionError('index_resolved: called on unresolved deps')

    node = self._data[node_ident_str]
    if node.state != _DepsState.RECEIVING_EVENTS:
      raise AssertionError(
          'index_resolved: called on dependencies not in RECEIVING_EVENTS:'
          f' {node.state}')

    if deps.resolution == RESOLUTION_SATISFIED:
      # Find all edges which are SATISFIED.
      satisfied_edges = {
        idx
        for idx, event in deps.resolution_events.items()
        if event.resolution == RESOLUTION_SATISFIED
      }
      # compute the set of edges which actually contributed to the successful
      # resolution of `deps`.
      #
      # For any given group, if the group itself is satisfied, this returns the
      # cumulative set of edges for that group; Otherwise if the group is not
      # satisfied, returns the empty set.
      def visit(group: Dependencies.Group) -> set[int]:
        edges = {idx for idx in group.edges if idx in satisfied_edges}
        groups: list[set[int]] = [
          visited for subgroup in group.groups
          if (visited := visit(subgroup))
        ]
        threshold = group.threshold or (len(group.edges) + len(group.groups))
        if len(edges) + len(groups) < threshold:
          return set()
        return edges.union(*groups)

      node.satisfied_edges_flat = {
        extract_ident_condition(deps.edges[idx])[0]
        for idx in visit(deps.predicate)
      }
      for target in node.satisfied_edges_flat:
        self._data[target].satisfied_dependents.add(node_ident_str)

    node.state = _DepsState.RESOLVED

  def dependencies_of(
      self,
      node_ident_str: str,
      mode: QueryExpandDepsMode,
  ) -> dict[str, identifier.Identifier]:
    """Returns nodes which `node_ident_str` depends on."""
    node = self._data[node_ident_str]
    edges: set[str]
    if mode == QueryExpandDepsMode.QUERY_EXPAND_DEPS_MODE_SATISFIED:
      edges = node.satisfied_edges_flat
    else:
      edges = node.edges_flat

    return {
        target_ident_str: to_id(target_ident_str) for target_ident_str in edges
    }

  def dependents_of(
      self,
      target_ident_str: str,
      mode: QueryExpandDepsMode,
  ) -> dict[str, identifier.Identifier]:
    """Return nodes which depend on `target_ident_str`."""
    node = self._data[target_ident_str]
    edges: set[str]
    if mode == QueryExpandDepsMode.QUERY_EXPAND_DEPS_MODE_SATISFIED:
      edges = node.satisfied_dependents
    else:
      edges = node.dependents

    return {
        node_ident_str: to_id(node_ident_str) for node_ident_str in edges
    }
