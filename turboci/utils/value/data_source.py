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
    super().__setitem__(
        key, pick_data(cur_data=self.get(key), new_data=data)
    )


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
      self._mapping[key] = pick_data(
          cur_data=self._mapping.get(key), new_data=value
      )

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
        self._mapping[key] = pick_data(
            cur_data=self._mapping.get(key), new_data=value
        )


def pick_data(
    cur_data: None | value_data_pb2.ValueData,
    new_data: value_data_pb2.ValueData,
) -> value_data_pb2.ValueData:
  """Selects and returns the higher quality ValueData between cur_data and
  new_data.

  If `new_data` is selected (or if `cur_data` is None), a deep copy of
  `new_data` is returned to ensure it owns its C++ backing memory and is
  decoupled from temporary RPC response lifetimes.
  """
  if not cur_data:
    copied = value_data_pb2.ValueData()
    copied.CopyFrom(new_data)
    return copied

  c_binary, c_json = cur_data.HasField('binary'), cur_data.HasField('json')
  n_binary, n_json = new_data.HasField('binary'), new_data.HasField('json')

  chosen = cur_data
  if c_binary and n_json:
    chosen = new_data
  elif c_json and n_binary:
    if (cur_data.json.has_unknown_fields and
        not new_data.json.has_unknown_fields):
      chosen = new_data
    else:
      chosen = cur_data
  elif c_json and not n_json:
    chosen = cur_data
  elif not cur_data.conversion_failure and new_data.conversion_failure:
    chosen = new_data

  # If new_data was selected, deep-copy it so it owns its C++ backing memory
  if chosen is not cur_data:
    copied = value_data_pb2.ValueData()
    copied.CopyFrom(chosen)
    return copied
  return cur_data
