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
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest

from .ids import from_id
from .edge import extract_ident_condition
from .errors import CheckWriteInvariantException


def _dup_types(vals: Sequence[WriteNodesRequest.RealmValue]) -> set[str]:
  count: dict[str, int] = defaultdict(int)
  for val in vals:
    count[val.value.value.type_url] += 1
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
      if write.HasField('dependencies') or state < CHECK_STATE_PLANNED:
        raise exc(
            f"new check: cannot add results in state {CheckState.Name(state)!r}"
        )
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
    elif old == CHECK_STATE_PLANNING and new == CHECK_STATE_PLANNED:
      pass
    elif old == CHECK_STATE_PLANNING and (not cur_has_deps or
                                          writing_empty_deps):
      # OK to go to WAITING/FINAL explicitly if there are no dependencies, or
      # we are writing an empty dependency set.
      pass
    elif old == CHECK_STATE_PLANNED:
      # This should always happen automatically - there's no reason to write to
      # a Check in the PLANNED state.
      unresolved_deps: set[str] = {
          extract_ident_condition(e)[0]
          for i, e in enumerate(check.dependencies.edges)
          if i not in check.dependencies.resolution_events
      }
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

  if write.HasField('dependencies'):
    if check.state != CHECK_STATE_PLANNING:
      raise exc(
          f"cannot edit dependencies in state {CheckState.Name(check.state)}")

    # write.dependencies is normalized by the calling function, so we don't need
    # to check for well-formedness here.

  if write.results or write.finalize_results:
    if check.state != CHECK_STATE_WAITING and (
        write.state != CHECK_STATE_WAITING and
        write.state != CHECK_STATE_FINAL):
      raise exc(f"cannot edit results in state {check.state}")
    if check.results and check.results[0].HasField('finalized_at'):
      raise exc(f"cannot edit finalized results")
