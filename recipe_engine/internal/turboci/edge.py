# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from typing import ClassVar, Literal, MutableSequence, Sequence
from itertools import chain

from google.protobuf.internal.containers import RepeatedCompositeFieldContainer

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.stage import Stage
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.edge_group import EdgeGroup
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.stage_state import StageState

from .ids import from_id


class GroupVisitor:
  """GroupVisitor is a visitor for a sequence of EdgeGroups.

  Override the methods in a subclass, then call `visit` with one or more
  EdgeGroups.
  """
  edge_filter: ClassVar[Literal['check', 'stage'] | None] = None

  def visit_group(self, group: EdgeGroup) -> bool:
    """Called before visiting groups or edges in `group`.

    Return False to skip visiting this group. If you return False, leave_group
    will not be called for this group.
    """
    return True

  def leave_group(self, group: EdgeGroup):
    """Called after handling all groups and edges in `group`.

    Not called if `visit_group` returned False for this `group`.
    """
    pass

  def visit_edge(self, edge: Edge):
    """Called for all Edge.

    If edge_filter was set on your subclass, only called for Edges which have
    that type of target.
    """
    pass

  def visit(self, *egs: EdgeGroup):
    """Walk `egs`, calling the visit and leave methods."""
    for group in egs:
      if not self.visit_group(group):
        continue
      self.visit(*group.groups)
      for edge in group.edges:
        if (self.edge_filter and
            edge.target.WhichOneof('type') != self.edge_filter):
          continue
        self.visit_edge(edge)
      self.leave_group(group)


def extract_target_ids(
    *groups: EdgeGroup,
    want: Literal['check', 'stage', '*'] = 'check',
    satisfied: bool | None = None,
) -> dict[str, identifier.Identifier]:
  """Given one or more EdgeGroups, find all identifier of the desired type.

  If `satisfied` is None, includes all edges.
  If `satisfied` is True, includes resolved, satisfied edges.
  If `satisfied` is False, includes resolved, unsatisfied edges.

  Returns a dict of stringified Identifier -> Identifier.
  """
  ret: dict[str, identifier.Identifier] = {}

  class _visitor(GroupVisitor):

    def visit_edge(self, edge: Edge):
      if satisfied is not None:
        if not edge.HasField('resolution'):
          return
        if edge.resolution.satisfied != satisfied:
          return
      if want == '*' or edge.target.WhichOneof('type') in want:
        if (ident_str := from_id(edge.target)) not in ret:
          ret[ident_str] = edge.target

  _visitor().visit(*groups)
  return ret


def resolve_edges(
    *groups: EdgeGroup,
    at: Revision,
    targets: Sequence[Check | Stage],
) -> bool | None:
  """Resolves edges which point to `target`.

  If `resolution` returns a bool, this will record it on the Edge along
  with `at` as the Resolution.

  Returns True iff all `groups` are satisfied at the end of the resolution phase.
  Returns False iff `groups` can never be satisfied.
  Returns None iff `groups` could be satisfied later.
  """
  target_map = {from_id(target.identifier): target for target in targets}

  def group_is_resolved(group: EdgeGroup) -> bool | None:
    if group.HasField('resolution'):
      return None

    # remaining is the number of edges/groups to check
    remaining = len(group.edges) + len(group.groups)
    # need is the number of satisfied edges/groups we need
    need_satisfied = group.threshold if group.threshold else remaining
    allow_unsatisfied = remaining - need_satisfied
    assert need_satisfied <= remaining, f"impossible: {need_satisfied=}>{remaining=}"

    for obj in chain(group.edges, group.groups):
      remaining -= 1
      if obj.HasField('resolution'):
        if obj.resolution.satisfied:
          need_satisfied -= 1
          if need_satisfied == 0:
            return True
        else:
          allow_unsatisfied -= 1
          if allow_unsatisfied < 0:
            return False
      elif need_satisfied > remaining:
        # We need to satisfy more slots than we have left to check, so this
        # group cannot be resolved yet.
        return None
    return True

  class _visitor(GroupVisitor):

    def visit_group(self, group: EdgeGroup) -> bool:
      return not group.HasField('resolution')

    def visit_edge(self, edge: Edge):
      if edge.HasField('resolution'):
        return

      target = target_map.get(from_id(edge.target))
      if not target:
        return

      match target:
        case Check():
          # Currently we only support FINAL -> satisfied, but other sorts of
          # conditions could occur in the future.
          #
          # NOTE: This duplicates logic with FakeTurboCIOrchestrator.update_indices_locked.
          if target.state != CheckState.CHECK_STATE_FINAL:
            return

        case Stage():
          # Currently we only support FINAL -> satisfied, but other sorts of
          # conditions could occur in the future.
          if target.state != StageState.STAGE_STATE_FINAL:
            return

      edge.resolution.satisfied = True
      edge.resolution.at.CopyFrom(at)

    def leave_group(self, group: EdgeGroup):
      if (satisfied := group_is_resolved(group)) is not None:
        group.resolution.satisfied = satisfied
        group.resolution.at.CopyFrom(at)

  _visitor().visit(*groups)
  if any(not group.HasField('resolution') for group in groups):
    return None
  return all(group.resolution.satisfied for group in groups)


def prune_empty_groups(groups: RepeatedCompositeFieldContainer[EdgeGroup]
                       | MutableSequence[EdgeGroup]):
  """Takes a mutable sequence of groups and trims it in-place to remove all
  empty groups.

  Empty groups are defined as having no edges and no contained groups.
  This will also normalize groups which contain exactly one other group to just
  be the contained group.
  """
  to_pop = []
  for i, group in enumerate(groups):
    prune_empty_groups(group.groups)
    if (len(group.groups) + len(group.edges)) == 0:
      to_pop.append(i)
    elif len(group.groups) == 1 and len(group.edges) == 0:
      # our group contains one group and no edges, we can absorb that group.
      group.CopyFrom(group.groups[0])
  for i in reversed(to_pop):
    groups.pop(i)
