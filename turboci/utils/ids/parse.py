# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines parsing and string serialization for TurboCI identifiers."""

from __future__ import annotations

__all__ = [
    'from_string',
    'to_string',
]

from google.protobuf import timestamp_pb2

from PB.turboci.graph.ids.v1 import identifier as identifier_pb2
from turboci.utils.ids import wrapping


def to_string(ident: wrapping.AnyIdentifier) -> str:
  """Converts from a proto identifier to a canonical string."""

  def fmt_rev(ts: timestamp_pb2.Timestamp) -> str:
    return f'{ts.seconds}/{ts.nanos}'

  any_id = wrapping.unwrap(ident)
  parts = []
  stop = False

  while not stop:
    match any_id:

      case identifier_pb2.WorkPlan():
        if any_id.id:
          parts.append(f'L{any_id.id}')
        stop = True

      case identifier_pb2.Check():
        parts.extend([f'{any_id.id}', ':C'])
        any_id = any_id.work_plan

      case identifier_pb2.CheckResult():
        parts.extend([f'{any_id.idx}', ':R'])
        any_id = any_id.check

      case identifier_pb2.CheckEdit():
        parts.extend([f'{fmt_rev(any_id.version)}', ':V'])
        any_id = any_id.check

      case identifier_pb2.Stage():
        pfx = ':?'
        if any_id.HasField('is_worknode'):
          pfx = ':N' if any_id.is_worknode else ':S'

        parts.extend([f'{any_id.id}', pfx])
        any_id = any_id.work_plan

      case identifier_pb2.StageAttempt():
        parts.extend([f'{any_id.idx}', ':A'])
        any_id = any_id.stage

      case identifier_pb2.StageEdit():
        parts.extend([f'{fmt_rev(any_id.version)}', ':V'])
        any_id = any_id.stage

      case _:
        raise NotImplementedError(f'to_string({type(id)})')

  parts.reverse()
  return ''.join(parts)


def from_string(ident_str: str) -> identifier_pb2.Identifier:
  """Converts from a canonical string identifier to a wrapped Identifier."""
  toks = ident_str.split(':')
  # trim are the tokens with the leading char removed
  trim = [t[1:] for t in toks]
  ret = identifier_pb2.Identifier()

  def parse_is_worknode(stg: identifier_pb2.Stage):
    """Parses toks[1][0] for S, N, ?"""
    match toks[1][0]:
      case 'N':
        stg.is_worknode = True
      case 'S':
        stg.is_worknode = False
      case '?':
        stg.ClearField('is_worknode')
      case _:
        raise NotImplementedError(
            'from_string: expected token to start with S, N or ?, '
            f'got {toks[1][0]!r}'
        )

  def parse_vers(v: str, to: timestamp_pb2.Timestamp):
    secs, nanos = v.split('/')
    to.seconds = int(secs)
    to.nanos = int(nanos)

  match [t[0] if t else '' for t in toks]:
    case ['L' | '']:
      if trim[0]:
        ret.work_plan.id = trim[0]

    case ['L' | '', 'C']:
      if trim[0]:
        ret.check.work_plan.id = trim[0]
      ret.check.id = trim[1]

    case ['L' | '', 'C', 'R']:
      if trim[0]:
        ret.check_result.check.work_plan.id = trim[0]
      ret.check_result.check.id = trim[1]
      ret.check_result.idx = int(trim[2])

    case ['L' | '', 'C', 'V']:
      if trim[0]:
        ret.check_edit.check.work_plan.id = trim[0]
      ret.check_edit.check.id = trim[1]
      parse_vers(trim[2], ret.check_edit.version)

    case ['L' | '', _]:
      if trim[0]:
        ret.stage.work_plan.id = trim[0]
      parse_is_worknode(ret.stage)
      ret.stage.id = trim[1]

    case ['L' | '', _, 'A']:
      if trim[0]:
        ret.stage_attempt.stage.work_plan.id = trim[0]
      parse_is_worknode(ret.stage_attempt.stage)
      ret.stage_attempt.stage.id = trim[1]
      ret.stage_attempt.idx = int(trim[2])

    case ['L' | '', _, 'V']:
      if trim[0]:
        ret.stage_edit.stage.work_plan.id = trim[0]
      parse_is_worknode(ret.stage_edit.stage)
      ret.stage_edit.stage.id = trim[1]
      parse_vers(trim[2], ret.stage_edit.version)

  if not ret.WhichOneof('type'):
    raise NotImplementedError(f'from_string: unrecognized ID {ident_str!r}')

  return ret
