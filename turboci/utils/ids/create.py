# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Convenience constructive helpers for TurboCI IDs."""

from __future__ import annotations

__all__ = [
    'check',
    'check_edit',
    'check_result',
    'stage',
    'stage_attempt',
    'stage_edit',
    'workplan',
]

import datetime

from google.protobuf import timestamp_pb2

from PB.turboci.graph.ids.v1 import identifier as identifier_pb2


def normalize_workplan(in_workplan: str | int | identifier_pb2.WorkPlan) -> str:
  """Converts 'L1345', '1345' and 1345 to '1345'.

  Rejects non-numeric workplan IDs with ValueError.

  Used by other modules, so doesn't have a leading underscore, but we don't
  need to export it via __all__.
  """
  if isinstance(in_workplan, int):
    return str(in_workplan)
  if isinstance(in_workplan, identifier_pb2.WorkPlan):
    return in_workplan.id
  s = in_workplan.lstrip('L')
  if s:
    try:
      int(s)
    except ValueError as exc:
      raise ValueError(
          f'work_plan: id must be parsable as an integer: {in_workplan!r}'
      ) from exc
  return s


def _check_index(idx: int):
  if idx <= 0 or idx >= 2**31 - 1:
    raise ValueError(f'index must be in [1, 2**31 - 1): {idx!r}')


def workplan(ident: str | int) -> identifier_pb2.WorkPlan:
  """Helper to construct a WorkPlan identifier.

  Args:
    ident: The workplan ID string (with or without 'L' prefix) or integer.
  """
  cleaned = normalize_workplan(ident)
  return identifier_pb2.WorkPlan(id=cleaned)


def check(
    ident: str, in_workplan: identifier_pb2.WorkPlan | None = None
) -> identifier_pb2.Check:
  """Helper to generate a Check identifier.

  Args:
    ident: The check ID string. Must not contain ':'.
    in_workplan: Optional workplan parent ID.
  """
  if ':' in ident:
    raise ValueError(f"check: value must not contain ':': {ident!r}")

  return identifier_pb2.Check(work_plan=in_workplan, id=ident)


def check_result(
    idx: int, check_id: identifier_pb2.Check
) -> identifier_pb2.CheckResult:
  """Helper to generate a CheckResult identifier.

  Args:
    idx: The result index.
    check_id: The Check identifier.
  """
  _check_index(idx)
  return identifier_pb2.CheckResult(check=check_id, idx=idx)


def check_edit(
    ts: datetime.datetime | timestamp_pb2.Timestamp,
    check_id: identifier_pb2.Check,
) -> identifier_pb2.CheckEdit:
  """Helper to generate a CheckEdit identifier_pb2.

  Args:
    ts: The edit timestamp, used as version.
    check_id: The Check identifier.
  """
  if isinstance(ts, datetime.datetime):
    tspb = timestamp_pb2.Timestamp()
    tspb.FromDatetime(ts)
    ts = tspb
  return identifier_pb2.CheckEdit(check=check_id, version=ts)


def stage(
    ident: str,
    in_workplan: identifier_pb2.WorkPlan | None = None,
    *,
    is_worknode: bool = False,
) -> identifier_pb2.Stage:
  """Helper to generate a Stage identifier_pb2.

  Args:
    ident: The stage ID string.
    in_workplan: Optional workplan parent ID.
    is_worknode: Whether the stage is a worknode.
  """
  if ':' in ident:
    raise ValueError(f"stage: value must not contain ':': {ident!r}")

  return identifier_pb2.Stage(
      work_plan=in_workplan, id=ident, is_worknode=is_worknode
  )


def stage_attempt(
    idx: int, stage_id: identifier_pb2.Stage
) -> identifier_pb2.StageAttempt:
  """Helper to generate a StageAttempt identifier.

  Args:
    idx: The attempt index.
    stage_id: The Stage identifier.
  """
  _check_index(idx)
  return identifier_pb2.StageAttempt(stage=stage_id, idx=idx)


def stage_edit(
    ts: datetime.datetime | timestamp_pb2.Timestamp,
    stage_id: identifier_pb2.Stage,
) -> identifier_pb2.StageEdit:
  """Helper to generate a StageEdit identifier.

  Args:
    ts: The edit timestamp, used as version.
    stage_id: The Stage identifier.
  """
  if isinstance(ts, datetime.datetime):
    tspb = timestamp_pb2.Timestamp()
    tspb.FromDatetime(ts)
    ts = tspb
  return identifier_pb2.StageEdit(stage=stage_id, version=ts)
