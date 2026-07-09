# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines functions for maintaining sorted ValueRef lists."""

from __future__ import annotations

__all__ = [
    'add_ref',
    'find',
    'find_all',
    'set_ref',
]

import typing
import bisect

from google.protobuf.internal import containers

from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2


def find_all(
    refs: typing.Sequence[value_ref_pb2.ValueRef], type_url: str
) -> tuple[int, typing.Sequence[value_ref_pb2.ValueRef]]:
  """Returns the index of the ref with type_url in a sorted set of refs.

  Args:
    refs: Must already be sorted by type_url. It is allowed to have duplicates
      by type_url, but they must all be contiguous.
    type_url: The type_url to search for.

  Returns
    (index, found). If found has entries, they are all refs which match.
    If found is empty, index is the index of where insertion of a new
    ref with `type_url` would go to maintain sort order.
  """
  start_idx = bisect.bisect_left(refs, type_url, key=lambda r: r.type_url)
  idx = start_idx
  while idx < len(refs) and refs[idx].type_url == type_url:
    idx += 1
  return start_idx, refs[start_idx:idx]


def find(
    refs: typing.Sequence[value_ref_pb2.ValueRef], type_url: str
) -> None | value_ref_pb2.ValueRef:
  """Finds the first matching ValueRef in a sorted set of ValueRefs.

  Note that ValueRefs do not need to be unique by type_url (such as for
  edit reason details).

  Args:
    refs: Sequence of ValueRef, sorted by `type_url`.
    type_url: The type of ValueRef to find.

  Returns:
    The found ref or None, if no non-omitted refs matched.
  """
  _, found = find_all(refs, type_url)
  for ref in found:
    if not ref.HasField('omit_reason'):
      return ref
  return None


def set_ref(
    refs: (
        typing.MutableSequence[value_ref_pb2.ValueRef]
        | containers.RepeatedCompositeFieldContainer[value_ref_pb2.ValueRef]
    ),
    ref: value_ref_pb2.ValueRef,
):
  """Adds or overrides `ref` in `refs` by type_url.

  Updates `refs` in place:
    * Replaces the entry with the same `type_url` if it exists.
    * Otherwise, inserts `ref`.

  The update will keep the sequence sorted by `type_url`.

  Args:
    refs: sequence of ValueRefs, expected to be sorted and unique by `type_url`.
    ref: The ref data to insert in this sequence.

  Raises:
    ValueError if `ref.type_url` is not unique in `refs`, or if an existing ref
      for the same type_url has a different realm than the provided `ref`.
  """
  start_idx, found = find_all(refs, ref.type_url)
  if len(found) > 1:
    raise ValueError(f'found more than one ref with {ref.type_url=!r}')

  if found:
    cur_ref = found[0]
    if cur_ref.realm != ref.realm:
      cur_realm = cur_ref.realm
      want_realm = ref.realm
      raise ValueError(
          f'mismatched realms with {ref.type_url=!r}: {cur_realm=!r}'
          f' {want_realm=!r}'
      )
    refs[start_idx].CopyFrom(ref)
  else:
    refs.insert(start_idx, ref)


def add_ref(
    refs: (
        typing.MutableSequence[value_ref_pb2.ValueRef]
        | containers.RepeatedCompositeFieldContainer[value_ref_pb2.ValueRef]
    ),
    ref: value_ref_pb2.ValueRef,
):
  """Adds `ref` in `refs`.

  Args:
    refs: MutableSequence of ValueRefs, sorted and unique by `type_url`. This
      will have `ref` inserted into it.
    ref: The ref data to insert in this sequence.

  Raises:
    ValueError if a ref with `ref.type_url` already exists in `refs`.
  """
  start_idx, found = find_all(refs, ref.type_url)
  if found:
    raise ValueError(f'{ref.type_url=!r} already in refs')
  refs.insert(start_idx, ref)
