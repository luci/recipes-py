# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Inspections for graphs and roots inside TurboCI identifiers."""

from __future__ import annotations

from PB.turboci.graph.ids.v1 import identifier as identifier_pb2
from turboci.utils.ids import wrapping

__all__ = [
    'root',
    'same_root',
    'same_workplan',
]


def root(
    ident: wrapping.AnyIdentifier,
) -> tuple[
    identifier_pb2.WorkPlan | None,
    identifier_pb2.Check | None,
    identifier_pb2.Stage | None,
]:
  """Returns the underlying root components representing the identifier.

  Useful to inspect the baseline components (WorkPlan, Check, or Stage)
  without type switches.

  Returns:
    A 3-tuple of (WorkPlan, Check, Stage) where precisely one of Check or Stage
   is populated.
  """
  match (unwrapped := wrapping.unwrap(ident)):
    case identifier_pb2.WorkPlan():
      return unwrapped, None, None
    case identifier_pb2.Check():
      return unwrapped.work_plan, unwrapped, None
    case identifier_pb2.CheckResult():
      return unwrapped.check.work_plan, unwrapped.check, None
    case identifier_pb2.CheckEdit():
      return unwrapped.check.work_plan, unwrapped.check, None
    case identifier_pb2.Stage():
      return unwrapped.work_plan, None, unwrapped
    case identifier_pb2.StageAttempt():
      return unwrapped.stage.work_plan, None, unwrapped.stage
    case identifier_pb2.StageEdit():
      return unwrapped.stage.work_plan, None, unwrapped.stage
    case _:
      raise NotImplementedError(f'root({type(ident)})')


def same_root(a: wrapping.AnyIdentifier, b: wrapping.AnyIdentifier) -> bool:
  """Checks if two identifiers share the exact same Check or Stage root."""
  if a is None or b is None:
    return False

  _, chk_a, stg_a = root(a)
  _, chk_b, stg_b = root(b)

  if chk_a and chk_b:
    return chk_a == chk_b
  if stg_a and stg_b:
    return stg_a == stg_b
  return False


def same_workplan(a: wrapping.AnyIdentifier, b: wrapping.AnyIdentifier) -> bool:
  """Checks if two identifiers operate within the same WorkPlan context."""
  if a is None or b is None:
    return False

  wp_a, _, _ = root(a)
  wp_b, _, _ = root(b)

  if wp_a and wp_b:
    return wp_a == wp_b
  return False
