# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from collections import defaultdict
from typing import Sequence

from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_state import (CHECK_STATE_PLANNING,
                                                          CHECK_STATE_PLANNED,
                                                          CHECK_STATE_WAITING,
                                                          CHECK_STATE_FINAL,
                                                          CheckState)
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.edge_group import EdgeGroup
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest

from . import edge
from .ids import from_id
from .errors import CheckWriteInvariantException


def _dup_types(vals: Sequence[WriteNodesRequest.RealmValue]) -> set[str]:
  count: dict[str, int] = defaultdict(int)
  for val in vals:
    count[val.value.type_url] += 1
  return {typ_url for typ_url, amt in count.items() if amt > 1}


def assert_can_apply(write: WriteNodesRequest.CheckWrite, check: None | Check):
  """Raises CheckWriteInvariantException if `write` cannot apply to `check`."""
  ident_str = from_id(write.identifier)
  exc = lambda msg: CheckWriteInvariantException(
      f"WriteNodes.CheckWrite({ident_str!r}): {msg}",)

  if ':' in write.identifier.id:
    raise exc('invalid identifier: contains ":"')

  if dups := _dup_types(write.options):
    raise exc(f'options: duplicate types: {dups}')

  if dups := _dup_types(write.results):
    raise exc(f'results: duplicate types: {dups}')

  if check is None:
    # This delta would create a new check, so `kind` is required.
    if not write.HasField('kind'):
      raise exc("new check: missing `kind`")

    # New checks have an implied PLANNING state unless the delta has something
    # different.
    state = write.state or CHECK_STATE_PLANNING

    # can set results as long as:
    #   * there are no dependencies
    #   * the target state is PLANNED or later.
    if write.results:
      if write.dependencies or state < CHECK_STATE_PLANNED:
        raise exc(f"new check: results for state {state!r}")
    return

  if (new := write.kind) and new != check.kind:
    raise exc(f"mismatched kind: {new} != {check.kind}")

  # None means 'don't update the field'
  dependencies: Sequence[EdgeGroup] | None = (None if not write.dependencies
                                              else write.dependencies)
  # If the user wants to clear dependencies, they will write a single, empty,
  # EdgeGroup. Prune all empty edge groups from `dependencies`.
  if dependencies:
    edge.prune_empty_groups(dependencies)

  if new := write.state:
    old = check.state
    if old == new:
      pass
    elif old == CHECK_STATE_PLANNING and new == CHECK_STATE_PLANNED:
      pass
    elif old == CHECK_STATE_PLANNING and (not check.dependencies or
                                          (dependencies is not None and
                                           not dependencies)):
      # OK to go to WAITING/FINAL explicitly if there are no dependencies, or
      # we are writing an empty dependency set.
      pass
    elif old == CHECK_STATE_PLANNED:
      # This should always happen automatically - there's no reason to write to
      # a Check in the PLANNED state.
      unresolved_deps: set[str] = set()

      class find_unresolved(edge.GroupVisitor):

        def visit_group(self, group: EdgeGroup) -> bool:
          return not group.resolution.satisfied

        def visit_edge(self, edge: Edge):
          if not edge.HasField('resolution'):
            unresolved_deps.add(from_id(edge.target))

      find_unresolved().visit(*check.dependencies)
      raise exc(
          f"PLANNED->WAITING happens automatically when all deps are resolved (missing {unresolved_deps})."
      )
    elif old == CHECK_STATE_WAITING and new == CHECK_STATE_FINAL:
      pass
    else:
      raise exc(f"invalid state transition: {CheckState.Name(check.state)} -> "
                f"{CheckState.Name(new)}")

  # Now, check that the rest of the fields specified are appropriate for
  # check.state.

  if write.options:
    if check.state != CHECK_STATE_PLANNING:
      raise exc(f"cannot edit options in state {CheckState.Name(check.state)}")

  if dependencies is not None:
    if check.state != CHECK_STATE_PLANNING:
      raise exc(
          f"cannot edit dependencies in state {CheckState.Name(check.state)}")

    class check_edge_group_well_formed(edge.GroupVisitor):

      def visit_group(self, group: EdgeGroup) -> bool:
        if group.HasField("resolution"):
          raise exc(f"written groups must not populate `resolution`")
        if (got := group.threshold) < 0:
          raise exc(f"written groups must have threshold >= 0: {got=}")
        if (got := group.threshold) > (want :=
                                       len(group.groups) + len(group.edges)):
          raise exc(
              "written groups must have threshold < #(groups)+#(edges): " +
              f"{got=} {want=}")
        return True

      def visit_edge(self, edge: Edge):
        if edge.HasField("resolution"):
          raise exc(f"written edges must not populate `resolution`")

    check_edge_group_well_formed().visit(*dependencies)

  if write.results or write.finalize_results:
    if check.state != CHECK_STATE_WAITING and (
        write.state != CHECK_STATE_WAITING and
        write.state != CHECK_STATE_FINAL):
      raise exc(f"cannot edit results in state {check.state}")
    if check.results and check.results[0].HasField('finalized_at'):
      raise exc(f"cannot edit finalized results")
