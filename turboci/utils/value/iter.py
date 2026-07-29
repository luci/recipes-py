# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helpers for iterating through the ValueRefs of TurboCI messages."""

import typing

from PB.turboci.graph.orchestrator.v1 import check as check_pb2
from PB.turboci.graph.orchestrator.v1 import edit as edit_pb2
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb2
from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from PB.turboci.graph.orchestrator.v1 import value_slot as value_slot_pb2
from PB.turboci.graph.orchestrator.v1 import workplan as workplan_pb2

__all__ = [
    'refs_in_check',
    'refs_in_edit',
    'refs_in_stage',
    'refs_in_stage_attempt',
    'refs_in_workplan',
]


def refs_in_stage(
    stage: stage_pb2.Stage,
) -> typing.Iterable[tuple[value_slot_pb2.ValueSlot, value_ref_pb2.ValueRef]]:
  if stage.HasField('args'):
    yield value_slot_pb2.VALUE_SLOT_STAGE_ARGS, stage.args

  if stage.legacy.HasField('worknode'):
    yield value_slot_pb2.VALUE_SLOT_STAGE_LEGACY_WORKNODE, stage.legacy.worknode

  for edit in stage.edits:
    yield from refs_in_edit(edit)

  for attempt in stage.attempts:
    yield from refs_in_stage_attempt(attempt)


def refs_in_edit(
    edit: edit_pb2.Edit,
) -> typing.Iterable[tuple[value_slot_pb2.ValueSlot, value_ref_pb2.ValueRef]]:
  slot = value_slot_pb2.VALUE_SLOT_CHECK_EDIT_REASON_DETAIL
  if edit.HasField('stage'):
    slot = value_slot_pb2.VALUE_SLOT_STAGE_EDIT_REASON_DETAIL
  for detail in edit.reason.details:
    yield slot, detail

  if slot == value_slot_pb2.VALUE_SLOT_STAGE_EDIT_REASON_DETAIL:
    for attempt in edit.stage.attempts:
      for detail in attempt.details:
        yield value_slot_pb2.VALUE_SLOT_STAGE_EDIT_ATTEMPT_DETAIL, detail
  else:
    for option in edit.check.options:
      yield value_slot_pb2.VALUE_SLOT_CHECK_EDIT_OPTION, option

    for result in edit.check.results:
      for dat in result.data:
        yield value_slot_pb2.VALUE_SLOT_CHECK_EDIT_RESULT_DATA, dat


def refs_in_stage_attempt(
    attempt: stage_pb2.Stage.Attempt,
) -> typing.Iterable[tuple[value_slot_pb2.ValueSlot, value_ref_pb2.ValueRef]]:
  for detail in attempt.details:
    yield value_slot_pb2.VALUE_SLOT_ATTEMPT_DETAIL, detail

  for progress in attempt.progress:
    for detail in progress.details:
      yield value_slot_pb2.VALUE_SLOT_ATTEMPT_PROGRESS_DETAIL, detail


def refs_in_check(
    check: check_pb2.Check,
) -> typing.Iterable[tuple[value_slot_pb2.ValueSlot, value_ref_pb2.ValueRef]]:
  for option in check.options:
    yield value_slot_pb2.VALUE_SLOT_CHECK_OPTION, option

  for result in check.results:
    for dat in result.data:
      yield value_slot_pb2.VALUE_SLOT_CHECK_RESULT_DATA, dat

  for edit in check.edits:
    yield from refs_in_edit(edit)


def refs_in_workplan(
    wp: workplan_pb2.WorkPlan,
) -> typing.Iterable[tuple[value_slot_pb2.ValueSlot, value_ref_pb2.ValueRef]]:
  for check in wp.checks:
    yield from refs_in_check(check)

  for stage in wp.stages:
    yield from refs_in_stage(stage)
