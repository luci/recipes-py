# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines DataSource and SimpleDataSource types and helpers."""

from __future__ import annotations

import collections
import threading
import typing

from PB.turboci.graph.orchestrator.v1 import value_data as value_data_pb2

__all__ = [
    'DataSource',
    'MutableDataSource',
    'SimpleDataSource',
    'LockedDataSource',
    'pick_data',
]


# Type definition used by reader/decoder functions in the value module.
#
# Keys are ValueRef digests.
DataSource = typing.Mapping[str, value_data_pb2.ValueData]


# Like DataSource, but mutable.
#
# Keys are ValueRef digests.
MutableDataSource = typing.MutableMapping[str, value_data_pb2.ValueData]


@typing.runtime_checkable
class _weakDataSource(typing.Protocol):
  """Absolutely bare minimum subset of Mapping[str, ValueData] for type

  definitions.
  """

  def __getitem__(self, key: str, /) -> value_data_pb2.ValueData:
    ...

  def keys(self) -> typing.Iterable[str]:
    ...


class SimpleDataSource(
    collections.UserDict[str, value_data_pb2.ValueData], MutableDataSource
):
  """A implementation of DataSource which uses `pick_data` to apply updates.

  This is *NOT* thread-safe. See LockedDataSource instead.

  Keys in this are `str`, but can be trivially cast to Digest.

  Assignment to this map uses `pick_data` to incorporate the assigned data
  instead of simple overwrites.

  If you plan on keeping a DataSource around between multiple calls, consider
  using this to minimize memory usage for overlapping data returned from
  multiple TurboCI RPCs.
  """

  def __setitem__(self, key: str, data: value_data_pb2.ValueData):
    """Incorporates `data` @ `key` into this SimpleDataSource.

    Uses `pick_data` to compute merged value.

    Args:
      key: The digest to update.
      data: The data to incorporate.
    """
    super().__setitem__(key, pick_data(self.get(key), data))


@typing.final
class LockedDataSource(MutableDataSource):
  """LockedDataSource is a MutableDataSource with a mutex.

  This purposefully does not extend UserDict to allow correct/efficient bulk
  operations (e.g. update, iter, etc.)
  """

  def __init__(
      self,
      *o: DataSource | typing.Iterable[tuple[str, value_data_pb2.ValueData]],
      **kwargs: value_data_pb2.ValueData,
  ) -> None:
    self._mu = threading.Lock()
    self._mapping: dict[str, value_data_pb2.ValueData] = dict(*o, **kwargs)

  def __iter__(self) -> typing.Iterator[str]:
    with self._mu:
      # We must copy the keys within the lock - otherwise a simultaneous write
      # could mutate the dict while iterating.
      return iter(list(self._mapping))

  def __len__(self) -> int:
    with self._mu:
      return len(self._mapping)

  def __getitem__(self, key: str, /) -> value_data_pb2.ValueData:
    with self._mu:
      return self._mapping[key]

  def __setitem__(self, key: str, value: value_data_pb2.ValueData) -> None:
    with self._mu:
      self._mapping[key] = pick_data(self._mapping.get(key), value)

  def __delitem__(self, key: str) -> None:
    with self._mu:
      del self._mapping[key]

  def items(self) -> typing.ItemsView[str, value_data_pb2.ValueData]:
    with self._mu:
      return dict(self._mapping).items()

  # pylint: disable=arguments-differ
  def update(
      self,
      *o: DataSource
      | _weakDataSource
      | typing.Iterable[tuple[str, value_data_pb2.ValueData]],
      **kwargs: value_data_pb2.ValueData,
  ) -> None:
    if len(o) > 1:
      raise TypeError(f'dict expected at most 1 argument, got {len(o):d}')
    # Prepare updates outside the lock to avoid deadlock if o[0] is another
    # LockedDataSource
    updates: list[tuple[str, value_data_pb2.ValueData]] = []
    if o:
      o0 = o[0]
      if isinstance(o0, typing.Mapping):
        # This might call o[0].items() which acquires o[0]._mu, but we don't
        # hold self._mu yet.
        updates.extend(typing.cast(DataSource, o0).items())
      elif isinstance(o0, _weakDataSource):
        for key in o0.keys():
          updates.append((key, o0[key]))
      elif isinstance(o0, typing.Iterable):
        updates.extend(
            typing.cast(
                typing.Iterable[tuple[str, value_data_pb2.ValueData]], o0
            )
        )
      else:
        raise ValueError(f'Unsupported type for update: {type(o0)}')
    for key, value in kwargs.items():
      updates.append((key, value))

    with self._mu:
      for key, value in updates:
        self._mapping[key] = pick_data(self._mapping.get(key), value)


def pick_data(
    a: None | value_data_pb2.ValueData, b: value_data_pb2.ValueData
) -> value_data_pb2.ValueData:
  """Returns either `a` or `b` depending on which is better.

  Both `a` and `b` must be well-formed (one of `binary` or `json` must be
  populated)

  Prefers JSON without unknown fields to JSON with unknown fields.
  Prefers JSON to binary data.
  Prefers binary data with conversion_failure enum to binary data without.

  Args:
    a: The left-hand-side ValueData (or None, if there is no current ValueData)
    b: The right-hand-side ValueData.

  Returns:
    The selected ValueData.
  """
  if not a:
    return b

  a_binary, a_json = a.HasField('binary'), a.HasField('json')
  b_binary, b_json = b.HasField('binary'), b.HasField('json')

  if a_binary and b_json:
    return b

  if a_json and b_binary:
    if a.json.has_unknown_fields and not b.json.has_unknown_fields:
      return b
    return a

  if a_json and not b_json:
    return a

  if not a.conversion_failure and b.conversion_failure:
    return b

  return a
