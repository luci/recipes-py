# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provides methods to wrap and unwrap specific identifier protos."""

from __future__ import annotations

__all__ = [
    'AnyIdentifier',
    'SpecificIdentifier',
    'unwrap',
    'wrap',
]

from PB.turboci.graph.ids.v1 import identifier as identifier_pb2

SpecificIdentifier = (
    identifier_pb2.WorkPlan
    | identifier_pb2.Check
    | identifier_pb2.CheckResult
    | identifier_pb2.CheckEdit
    | identifier_pb2.Stage
    | identifier_pb2.StageAttempt
    | identifier_pb2.StageEdit
)

AnyIdentifier = identifier_pb2.Identifier | SpecificIdentifier


def wrap(ident: AnyIdentifier) -> identifier_pb2.Identifier:
  """Wraps a specific identifier type into a generic Identifier wrapper.

  Args:
    ident: The specific identifier subclass or Identifier itself.

  Returns:
    An enveloped Identifier proto.
  """
  match ident:
    case identifier_pb2.Identifier():
      return ident
    case identifier_pb2.WorkPlan():
      return identifier_pb2.Identifier(work_plan=ident)
    case identifier_pb2.Check():
      return identifier_pb2.Identifier(check=ident)
    case identifier_pb2.CheckResult():
      return identifier_pb2.Identifier(check_result=ident)
    case identifier_pb2.CheckEdit():
      return identifier_pb2.Identifier(check_edit=ident)
    case identifier_pb2.Stage():
      return identifier_pb2.Identifier(stage=ident)
    case identifier_pb2.StageAttempt():
      return identifier_pb2.Identifier(stage_attempt=ident)
    case identifier_pb2.StageEdit():
      return identifier_pb2.Identifier(stage_edit=ident)
    case _:
      raise NotImplementedError(f'wrap({type(ident)})')


def unwrap(ident: AnyIdentifier) -> SpecificIdentifier | None:
  """Unwraps any Identifier into it's *specific* identifier type.

  Args:
    ident: any Identifier.

  Returns:
    The *specific* identifier_pb2.
  """
  if not isinstance(ident, identifier_pb2.Identifier):
    return ident

  active_field = ident.WhichOneof('type')
  if not active_field:
    raise ValueError('unwrap: blank or unset Identifier wrapper')
  return getattr(ident, active_field)
