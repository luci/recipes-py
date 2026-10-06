# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import collections
from collections.abc import Sequence

from turboci.utils import ids

from PB.turboci.graph.orchestrator.v1 import check as check_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import value_write as value_write_pb
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_request as write_nodes_request_pb,
)

from . import edge
from . import errors


def _dup_types(vals: Sequence[value_write_pb.ValueWrite]) -> set[str]:
  count: dict[str, int] = collections.defaultdict(int)
  for val in vals:
    count[val.data.type_url] += 1
  return {typ_url for typ_url, amt in count.items() if amt > 1}


def assert_can_apply(
    write: write_nodes_request_pb.WriteNodesRequest.CheckWrite,
    check: check_pb.Check | None,
) -> None:
  """Raises RPCError if `write` cannot apply to `check`."""
  ident_str = ids.to_string(write.identifier)
  exc = lambda msg: errors.InvalidArgumentException(
      f"WriteNodes.CheckWrite({ident_str!r}): {msg}",)

  if ':' in write.identifier.id:
    raise exc('invalid identifier: contains ":"')

  if dups := _dup_types(write.options):
    raise exc(f'options: duplicate types: {dups}')

  if dups := _dup_types(write.result_data):
    raise exc(f'results: duplicate types: {dups}')

  if check is None:
    # This delta would create a new check, so `kind` is required.
    if not write.HasField('kind'):
      raise exc("new check: missing `kind`")

    # New checks have an implied PLANNING state unless the delta has something
    # different.
    state = write.state or check_state_pb.CHECK_STATE_PLANNING

    # can set results as long as:
    #   * there are no dependencies
    #   * the target state is PLANNED or later.
    if write.result_data:
      if (
          write.HasField('dependencies')
          or state < check_state_pb.CHECK_STATE_PLANNED
      ):
        state_name = check_state_pb.CheckState.Name(state)
        raise exc(f"new check: cannot add results in state {state_name!r}")
    return

  if (new := write.kind) and new != check.kind:
    raise exc(f"mismatched kind: {new} != {check.kind}")

  cur_has_deps = bool(check.dependencies.edges)
  writing_empty_deps = (
      write.HasField('dependencies') and
      (len(write.dependencies.edges) + len(write.dependencies.groups)) == 0)

  if new := write.state:
    old = check.state
    if old == new:
      pass
    elif (
        old == check_state_pb.CHECK_STATE_PLANNING
        and new == check_state_pb.CHECK_STATE_PLANNED
    ):
      pass
    elif old == check_state_pb.CHECK_STATE_PLANNING and (
        not cur_has_deps or writing_empty_deps
    ):
      # OK to go to WAITING/FINAL explicitly if there are no dependencies, or
      # we are writing an empty dependency set.
      pass
    elif old == check_state_pb.CHECK_STATE_PLANNED:
      # This should always happen automatically - there's no reason to write to
      # a Check in the PLANNED state.
      unresolved_deps: set[str] = {
          edge.extract_ident_condition(e)[0]
          for i, e in enumerate(check.dependencies.edges)
          if i not in check.dependencies.resolution_events
      }
      raise exc(
          "PLANNED->WAITING happens automatically when all deps are resolved "
          f"(missing {unresolved_deps})."
      )
    elif (
        old == check_state_pb.CHECK_STATE_WAITING
        and new == check_state_pb.CHECK_STATE_FINAL
    ):
      pass
    else:
      old_name = check_state_pb.CheckState.Name(check.state)
      new_name = check_state_pb.CheckState.Name(new)
      raise exc(f"invalid state transition: {old_name} -> {new_name}")

  # Now, check that the rest of the fields specified are appropriate for
  # check.state.

  if write.options:
    if check.state != check_state_pb.CHECK_STATE_PLANNING:
      state_name = check_state_pb.CheckState.Name(check.state)
      raise exc(f"cannot edit options in state {state_name}")

  if write.HasField('dependencies'):
    if check.state != check_state_pb.CHECK_STATE_PLANNING:
      state_name = check_state_pb.CheckState.Name(check.state)
      raise exc(f"cannot edit dependencies in state {state_name}")

    # write.dependencies is normalized by the calling function, so we don't need
    # to check for well-formedness here.

  if write.result_data or write.finalize_results:
    if check.state != check_state_pb.CHECK_STATE_WAITING and (
        write.state != check_state_pb.CHECK_STATE_WAITING
        and write.state != check_state_pb.CHECK_STATE_FINAL
    ):
      raise exc(f"cannot edit results in state {check.state}")
    if check.results and check.results[0].HasField('finalized_at'):
      raise exc("cannot edit finalized results")
