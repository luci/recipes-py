# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helpers for iterating through the ValueRefs of TurboCI messages."""

import enum
import typing

from PB.turboci.graph.orchestrator.v1 import check as check_pb2
from PB.turboci.graph.orchestrator.v1 import edit as edit_pb2
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb2
from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from PB.turboci.graph.orchestrator.v1 import workplan as workplan_pb2

__all__ = [
    'RefSlot',
    'refs_in_check',
    'refs_in_edit',
    'refs_in_stage',
    'refs_in_stage_attempt',
    'refs_in_workplan',
]


class RefSlot(enum.Enum):
  # StageArgs indicates the ValueRef is from `Stage.args`.
  StageArgs = 0
  # StageLegacyWorkNode indicates the ValueRef is from
  # `Stage.legacy.worknode`.
  StageLegacyWorkNode = 1

  # StageEditReasonDetails indicates the ValueRef is from
  # `Stage.edits.reason.details`.
  StageEditReasonDetails = 2
  # StageEditAttemptDetails indicates the ValueRef is from
  # `Stage.edits.stage.attempts.details`.
  StageEditAttemptDetails = 3

  # StageAttemptDetails indicates the ValueRef is from
  # `Stage.attempts.details`.
  StageAttemptDetails = 4
  # StageAttemptProgressDetails indicates the ValueRef is from
  # `Stage.attempts.progress.details`.
  StageAttemptProgressDetails = 5

  # CheckOptions indicates the ValueRef is from `Check.options`.
  CheckOptions = 6
  # CheckResultsData indicates the ValueRef is from `Check.results.data`.
  CheckResultsData = 7
  # CheckEditReasonDetails indicates the ValueRef is from
  # `Check.edits.reason.details`.
  CheckEditReasonDetails = 8
  # CheckEditOptions indicates the ValueRef is from
  # `Check.edits.check.options`.
  CheckEditOptions = 9
  # CheckEditResultsData indicates the ValueRef is from
  # `Check.edits.check.results.data`.
  CheckEditResultsData = 10


def refs_in_stage(
    stage: stage_pb2.Stage,
) -> typing.Generator[tuple[RefSlot, value_ref_pb2.ValueRef], None, None]:
  if stage.HasField('args'):
    yield RefSlot.StageArgs, stage.args

  if stage.legacy.HasField('worknode'):
    yield RefSlot.StageLegacyWorkNode, stage.legacy.worknode

  for edit in stage.edits:
    yield from refs_in_edit(edit)

  for attempt in stage.attempts:
    yield from refs_in_stage_attempt(attempt)


def refs_in_edit(
    edit: edit_pb2.Edit,
) -> typing.Generator[tuple[RefSlot, value_ref_pb2.ValueRef], None, None]:
  slot = RefSlot.CheckEditReasonDetails
  if edit.HasField('stage'):
    slot = RefSlot.StageEditReasonDetails
  for detail in edit.reason.details:
    yield slot, detail

  if slot == RefSlot.StageEditReasonDetails:
    for attempt in edit.stage.attempts:
      for detail in attempt.details:
        yield RefSlot.StageEditAttemptDetails, detail
  else:
    for option in edit.check.options:
      yield RefSlot.CheckEditOptions, option

    for result in edit.check.results:
      for dat in result.data:
        yield RefSlot.CheckEditResultsData, dat


def refs_in_stage_attempt(
    attempt: stage_pb2.Stage.Attempt,
) -> typing.Generator[tuple[RefSlot, value_ref_pb2.ValueRef], None, None]:
  for detail in attempt.details:
    yield RefSlot.StageAttemptDetails, detail

  for progress in attempt.progress:
    for detail in progress.details:
      yield RefSlot.StageAttemptProgressDetails, detail


def refs_in_check(
    check: check_pb2.Check,
) -> typing.Generator[tuple[RefSlot, value_ref_pb2.ValueRef], None, None]:
  for option in check.options:
    yield RefSlot.CheckOptions, option

  for result in check.results:
    for dat in result.data:
      yield RefSlot.CheckResultsData, dat

  for edit in check.edits:
    yield from refs_in_edit(edit)


def refs_in_workplan(
    wp: workplan_pb2.WorkPlan,
) -> typing.Generator[tuple[RefSlot, value_ref_pb2.ValueRef], None, None]:
  for check in wp.checks:
    yield from refs_in_check(check)

  for stage in wp.stages:
    yield from refs_in_stage(stage)
