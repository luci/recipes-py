# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""The turboci module implements a client for the TurboCI service whose

API protos are at:

  https://chromium.googlesource.com/infra/turboci/proto

Usage:

    from recipe_engine import turboci

    def RunSteps(...):
      turboci.query_nodes(...)
      turboci.write_nodes(...)

    def GenTests(api):
      api.test(
        'name',
        api.assert_workplan(...),
      )
"""

import typing

from google.protobuf.message import Message
from PB.turboci.graph.ids.v1 import identifier as _identifier
from PB.turboci.graph.orchestrator.v1 import type_set as _type_set
from PB.turboci.graph.orchestrator.v1 import check as _check
from turboci.utils import ids as _ids
from turboci.utils import value as _value
from turboci.utils import client as _client


def from_id(ident: _ids.AnyIdentifier) -> str:
  return _ids.to_string(ident)


def to_id(ident_str: str) -> _identifier.Identifier:
  return _ids.from_string(ident_str)


def type_url_for(msg: type[Message] | Message) -> str:
  return _value.url(msg)


def type_urls(*msgs: str | type[Message] | Message) -> typing.Iterable[str]:
  return (x if isinstance(x, str) else _value.url(x) for x in msgs)


def type_set(*msgs: str | type[Message] | Message) -> _type_set.TypeSet:
  return _type_set.TypeSet(type_urls=list(type_urls(*msgs)))


def wrap_id(ident: _ids.AnyIdentifier) -> _identifier.Identifier:
  return _ids.wrap(ident)


def check_id(id: str, *, in_workplan: str = '') -> _identifier.Check:
  return _ids.check(id, _ids.workplan(in_workplan) if in_workplan else None)


def collect_check_ids(
    *idents: _identifier.Check | str, in_workplan: str = ''
) -> typing.Iterable[_identifier.Identifier]:
  wp = _ids.workplan(in_workplan) if in_workplan else None
  for id in idents:
    if not isinstance(id, _identifier.Check):
      id = _ids.check(id, wp)
    yield _ids.wrap(id)

_MsgT = typing.TypeVar('_MsgT', bound=Message)

def get_option(msg: typing.Type[_MsgT], check: _check.Check) -> _MsgT | None:
  return _value.lookup({}, check.options, msg)

def get_results(msg: typing.Type[_MsgT], check: _check.Check) -> list[_MsgT]:
  return _value.results({}, check, msg)


from .internal.turboci.common import (
    TurboCIClient,
    check,
    dep_group,
    get_check_by_short_id,
    make_query,
    query_nodes,
    read_checks,
    reason,
    write_nodes,
)

# These are all catchable as client.RPCError now.
TransactionConflictException = _client.TransactionalPreconditionError
InvalidArgumentException = _client.RPCError
CheckWriteInvariantException = _client.RPCError
TurboCIException = _client.RPCError

TransactionUseAfterWriteException = _client.TransactionMultipleWritesError

from recipe_engine.internal.turboci import common as _common


def get_client() -> TurboCIClient:
  """Gets the current raw client interface."""
  return _common.CLIENT


__all__ = [
    'CheckWriteInvariantException',
    'InvalidArgumentException',
    'TransactionConflictException',
    'TransactionUseAfterWriteException',
    'TurboCIException',
    'check',
    'check_id',
    'collect_check_ids',
    'dep_group',
    'from_id',
    'get_check_by_short_id',
    'get_client',
    'get_option',
    'get_results',
    'make_query',
    'query_nodes',
    'read_checks',
    'reason',
    'to_id',
    'type_set',
    'type_url_for',
    'type_urls',
    'wrap_id',
    'write_nodes',
]
