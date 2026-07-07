# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines decode, lookup and find."""

from __future__ import annotations

__all__ = [
    'decode',
    'lookup',
    'results',
]


import typing

from google.protobuf import any_pb2
from google.protobuf import message
from google.protobuf import json_format

from PB.turboci.graph.orchestrator.v1 import check as check_pb2
from PB.turboci.graph.orchestrator.v1 import value_data as value_data_pb2
from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from turboci.utils import value
from turboci.utils.value import data_source
from turboci.utils.value import ordered


T = typing.TypeVar('T', bound=message.Message)


def decode(
    ds: data_source.DataSource, ref: value_ref_pb2.ValueRef, msg: type[T]
) -> T:
  """Decode decodes and returns a proto of type `msg` from the given ValueRef.

  Args:
    ds: A DataSource used to pull ValueData by digest.
    ref: The ValueRef to decode.
    msg: The expected message type to decode.

  Raises:
    ValueError: If the type of the ref does not match the type of `msg`.
    protobuf.DecodeError: If the data cannot be decoded.
  """
  if ref.type_url != (targ_url := value.url(msg)):
    raise ValueError(
        f'cannot decode ValueRef[{ref.type_url}] into {targ_url!r}.'
    )

  bin_data: None | any_pb2.Any = None
  json_data: None | value_data_pb2.ValueData.JsonAny = None
  if ref.HasField('inline'):
    bin_data = ref.inline

  if ref.HasField('digest') and bin_data is None:
    try:
      got = ds[ref.digest]
      if got.HasField('binary'):
        bin_data = got.binary
      elif got.HasField('json'):
        json_data = got.json
    except KeyError:
      pass

  if not bin_data and not json_data:
    raise ValueError(f'could not find data for ValueRef[{ref.type_url}]')

  if bin_data:
    ret = msg()
    assert bin_data.Unpack(ret), f'failed to unpack {ref.type_url!r}'
    return ret

  assert json_data
  assert (
      json_data.type_url == ref.type_url
  ), f'BUG: mismatched refs {json_data.type_url!r} vs {ref.type_url!r}'

  ret = msg()
  json_format.Parse(json_data.value, ret)
  return ret


def lookup(
    ds: data_source.DataSource,
    refs: typing.Sequence[value_ref_pb2.ValueRef],
    msg: type[T],
) -> None | T:
  """Finds and decodes the first non-omitted ValueRef of type `T`.

  ValueRefs sorted by type_url.

  Note that ValueRefs do not need to be unique by type_url (such as for
  edit reason details).

  This assumes that `set` is sorted by "type_url" and will do a binary search.

  Args:
    ds: A DataSource used to pull ValueData by digest.
    refs: Sequence of ValueRef, sorted by type_url.
    msg: The type of ValueRef to find.

  Returns:
    The found and decoded ref or None, if no non-omitted refs matched.
  """
  val = ordered.find(refs, value.url(msg))
  if val:
    return decode(ds, val, msg)
  return None


def results(
    ds: data_source.DataSource,
    check: check_pb2.Check,
    msg: type[T],
) -> list[T]:
  """Collects all result data from the Check of type T.

  Args:
    ds: A DataSource used to pull ValueData by digest.
    refs: Sequence of ValueRef, sorted by type_url.
    msg: The type of ValueRef to find.

  Returns:
    All non-omitted result data in this Check which match `msg` (which may be
    none).
  """
  ret = []
  for rslt in check.results:
    if x := lookup(ds, rslt.data, msg):
      ret.append(x)
  return ret
