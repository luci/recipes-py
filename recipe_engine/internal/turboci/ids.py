# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Implements helpers for working with TurboCI identifiers."""

from __future__ import annotations

from typing import Generator, TypeVar

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.type_set import TypeSet
from recipe_engine.internal.turboci.errors import InvalidArgumentException


_TYPE_PREFIX = "type.googleapis.com/"


def type_url_for(msg: type[Message] | Message) -> str:
  """Returns the Any type_url value for a Message class or Message instance."""
  return f'{_TYPE_PREFIX}{msg.DESCRIPTOR.full_name}'


def type_urls(*msgs: str|type[Message]|Message) -> Generator[str]:
  """Cast multiple proto message types or instances to their type url."""
  for msg in msgs:
    if isinstance(msg, str):
      # * is a special value which means "all types"
      if msg != '*' and not msg.startswith(_TYPE_PREFIX):
        raise ValueError(f"type url {msg!r} must start with {_TYPE_PREFIX!r}.")
      yield msg
    else:
      yield type_url_for(msg)


def type_set(*msgs: str|type[Message]|Message) -> TypeSet:
  """Convenience function to turn a list of type strings/messages into a
  TurboCI TypeSet.
  """
  return TypeSet(type_urls=list(type_urls(*msgs)))


AnyIdentifier = (
    identifier.Identifier
    | identifier.WorkPlan
    | identifier.Check
    | identifier.CheckResult

  # Unsupported in the fake for now:
    | identifier.CheckEdit
    | identifier.Stage
    | identifier.StageAttempt
    | identifier.StageEdit
)


_CheckOrStage = TypeVar('_CheckOrStage', identifier.Check, identifier.Stage)

def _make_id_impl(typ: type[_CheckOrStage], id: str, in_workplan: str) -> _CheckOrStage:
  kind = typ.__name__.lower().split('.')[-1]

  ret = typ(id=id)
  if ':' in id:
    raise ValueError(f'{kind}_id: id value must not contain ":": {id!r}')

  if kind == 'stage':
    if not id.startswith(('N', 'S')):
      raise ValueError(f'{kind}_id: does not start with N or S: {id!r}')

  ret.id = id
  in_workplan = in_workplan.lstrip('L')
  if in_workplan:
    try:
      int(in_workplan)
    except ValueError as ex:
      ex.add_note(
          f'{kind}_id: in_workplan: id must be parsable as an integer: {in_workplan!r}')
      raise
    ret.work_plan.id = in_workplan
  return ret


def check_id(id: str, *, in_workplan: str = "") -> identifier.Check:
  """Helper to generate an identifier.Check (optionally, in a specific
  workplan).

  If provided, `in_workplan` may or may not contain the leading 'L'.
  """
  return _make_id_impl(identifier.Check, id, in_workplan)


def stage_id(id: str, *, in_workplan: str = "", is_worknode: bool = False) -> identifier.Stage:
  """Helper to generate an identifier.Stage (optionally, in a specific
  workplan).

  The resulting ID will have the 'S' tag, unless is_worknode is True, in which
  case it will be given the 'N' tag.

  If provided, `in_workplan` may or may not contain the leading 'L'.
  """
  tag = 'N' if is_worknode else 'S'
  return _make_id_impl(identifier.Stage, tag+id, in_workplan)


def from_id(ident: AnyIdentifier) -> str:
  """Converts from a proto identifier to a canonical string."""
  def fmt_rev(ts: Timestamp) -> str:
    return f'{ts.seconds}/{ts.nanos}'

  match ident:
    case identifier.Identifier():
      return from_id(getattr(ident, ident.WhichOneof('type')))

    case identifier.WorkPlan():
      return f'L{ident.id}'

    case identifier.Check():
      return f'{from_id(ident.work_plan)}:C{ident.id}'

    case identifier.CheckResult():
      return f'{from_id(ident.check)}:R{ident.idx}'

    case identifier.CheckEdit():
      return f'{from_id(ident.check)}:V{fmt_rev(ident.version)}'

    case identifier.Stage():
      pfx = '?'
      if ident.HasField('is_worknode'):
        pfx = 'N' if ident.is_worknode else 'S'
      return f'{from_id(ident.work_plan)}:{pfx}{ident.id}'

    case identifier.StageAttempt():
      return f'{from_id(ident.stage)}:A{ident.idx}'

    case identifier.StageEdit():
      return f'{from_id(ident.stage)}:V{fmt_rev(ident.version)}'

    case _:
      raise NotImplementedError(f'from_id({type(ident)})')


def to_id(ident_str: str) -> identifier.Identifier:
  """Converts from a canonical string identifier to a proto identifier."""
  toks = ident_str.split(':')
  # trim are the tokens with the leading char removed
  trim = [t[1:] for t in toks]
  ret = identifier.Identifier()

  def parse_is_worknode(stg: identifier.Stage):
    '''Parses toks[1][0] for S, N, ?'''
    match toks[1][0]:
      case 'N':
        stg.is_worknode = True
      case 'S':
        stg.is_worknode = False
      case '?':
        stg.ClearField('is_worknode')
      case _:
        raise InvalidArgumentException(
            f"Expected token to start with S, N or ?, got {toks[1][0]!r}")

  def parse_vers(v: str, to: Timestamp):
    secs, nanos = v.split('/')
    to.seconds = int(secs)
    to.nanos = int(nanos)

  match [t[0] for t in toks]:
    case ['L']:
      if trim[0]:
        ret.work_plan.id = trim[0]

    case ['L', 'C']:
      if trim[0]:
        ret.check.work_plan.id = trim[0]
      ret.check.id = trim[1]

    case ['L', 'C', 'R']:
      if trim[0]:
        ret.check_result.check.work_plan.id = trim[0]
      ret.check_result.check.id = trim[1]
      ret.check_result.idx = int(trim[2])

    case ['L', 'C', 'V']:
      if trim[0]:
        ret.check_edit.check.work_plan.id = trim[0]
      ret.check_edit.check.id = trim[1]
      parse_vers(trim[2], ret.check_edit.version )

    case ['L', _]:
      if trim[0]:
        ret.stage.work_plan.id = trim[0]
      parse_is_worknode(ret.stage)
      ret.stage.id = trim[1]

    case ['L', _, 'A']:
      if trim[0]:
        ret.stage_attempt.stage.work_plan.id = trim[0]
      parse_is_worknode(ret.stage_attempt.stage)
      ret.stage_attempt.stage.id = trim[1]
      ret.stage_attempt.idx = int(trim[2])

    case ['L', _, 'V']:
      if trim[0]:
        ret.stage_edit.stage.work_plan.id = trim[0]
      parse_is_worknode(ret.stage_edit.stage)
      ret.stage_edit.stage.id = trim[1]
      parse_vers(trim[2], ret.stage_edit.version)

  if not ret.WhichOneof('type'):
    raise NotImplementedError(f'to_id: unrecognized ID {ident_str!r}')

  return ret


def wrap_id(ident: AnyIdentifier) -> identifier.Identifier:
  """Wraps a specific identifier type into an Identifier."""
  match ident:
    case identifier.Identifier():
      return ident
    case identifier.WorkPlan():
      return identifier.Identifier(work_plan=ident)
    case identifier.Check():
      return identifier.Identifier(check=ident)
    case identifier.CheckResult():
      return identifier.Identifier(check_result=ident)
    case identifier.CheckEdit():
      return identifier.Identifier(check_edit=ident)
    case identifier.Stage():
      return identifier.Identifier(stage=ident)
    case identifier.StageAttempt():
      return identifier.Identifier(stage_attempt=ident)
    case identifier.StageEdit():
      return identifier.Identifier(stage_edit=ident)
    case _:
      raise NotImplementedError(f'wrap_id({type(ident)})')


def collect_check_ids(*ids: identifier.Check|str, in_workplan: str = "") -> Generator[identifier.Identifier]:
  """Collect a sequence of string or proto Check ids into Identifier protos.

  String IDs are handled with `check_id()`.
  """
  for ident in ids:
    if isinstance(ident, str):
      ident = check_id(ident, in_workplan=in_workplan)
    yield wrap_id(ident)
