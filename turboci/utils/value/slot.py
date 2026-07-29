# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines SlotSet an immutable bitmask representing sets of ValueSlot enums."""

from __future__ import annotations

import typing

from PB.turboci.graph.orchestrator.v1 import value_slot as value_slot_pb2

__all__ = [
    'SlotSet',
]


class SlotSet:
  """An immutable set of ValueSlot enums."""

  _mask: int
  _full_mask: typing.ClassVar[int]

  def __init__(self, *slots: value_slot_pb2.ValueSlot) -> None:
    """Optionally initializes the SlotSet with a sequence of ValueSlots."""
    if slots:
      self._mask = SlotSet().set(*slots)._mask
    else:
      self._mask = 0

  def _make(self, mask: int) -> typing.Self:
    # pylint: disable=protected-access
    ret = self.__class__()
    ret._mask = mask
    return ret

  @classmethod
  def _assert_slot_is_valid(cls, slot: int) -> bool:
    """Raises ValueError if slot is out of [0, 64].

    Returns True iff slot != UNKNOWN (0).
    """
    if slot < 0 or slot > value_slot_pb2.VALUE_SLOT_ALL:
      raise ValueError(
          f'ValueSlot out of range [1, {value_slot_pb2.VALUE_SLOT_ALL}]: {slot}'
      )
    return slot != 0

  def has_all(self, *slots: int) -> bool:
    """Returns True if all slots are present in the set."""
    mask = self._mask
    for slot in slots:
      if self._assert_slot_is_valid(slot):
        if slot == value_slot_pb2.VALUE_SLOT_ALL:
          return (mask & self._full_mask) == self._full_mask
        if not mask & (1 << (slot - 1)):
          return False
    return True

  def has_any(self, *slots: int) -> bool:
    """Returns True if at least one of the slots is present in the set."""
    mask = self._mask
    for slot in slots:
      if self._assert_slot_is_valid(slot):
        if slot == value_slot_pb2.VALUE_SLOT_ALL:
          return bool(mask & self._full_mask)
        if mask & (1 << (slot - 1)):
          return True
    return False

  def __contains__(self, slot: int) -> bool:
    """Supports `VALUE_SLOT_XXX in slot_set`."""
    return self.has_all(slot)

  def set(self, *slots: int) -> typing.Self:
    """Returns a new set with the specified slots added."""
    mask = self._mask
    for slot in slots:
      if self._assert_slot_is_valid(slot):
        if slot == value_slot_pb2.VALUE_SLOT_ALL:
          return self._make(self._full_mask)
        mask |= 1 << (slot - 1)
    return self._make(mask)

  def unset(self, *slots: int) -> typing.Self:
    """Returns a new set with the specified slots removed."""
    mask = self._mask
    for slot in slots:
      if self._assert_slot_is_valid(slot):
        if slot == value_slot_pb2.VALUE_SLOT_ALL:
          return self._make(0)
        mask &= ~(1 << (slot - 1))
    return self._make(mask)

  def __iter__(self) -> typing.Iterator[int]:
    """Iterates through the set slot enums in ascending order."""
    mask = self._mask
    while mask:
      lsb = mask & -mask
      yield lsb.bit_length()
      mask ^= lsb

  def _slot_name(self, slot: int) -> str:
    try:
      return value_slot_pb2.ValueSlot.Name(slot).removeprefix('VALUE_SLOT_')
    except ValueError:
      return f'value.SlotSet({slot})'

  def __eq__(self, value: object, /) -> bool:
    return isinstance(value, SlotSet) and value._mask == self._mask

  @property
  def _slot_list_str(self) -> str:
    return ', '.join(map(self._slot_name, self))

  def __str__(self) -> str:
    return f'value.SlotSet{{{self._slot_list_str}}}'

  def __repr__(self) -> str:
    return f'value.SlotSet[0x{self._mask:x}]{{{self._slot_list_str}}}'


# pylint: disable=protected-access
SlotSet._full_mask = (
    SlotSet()
    .set(*(
        slot
        for slot in value_slot_pb2.ValueSlot.values()
        if slot not in (0, value_slot_pb2.VALUE_SLOT_ALL)
    ))
    ._mask
)
