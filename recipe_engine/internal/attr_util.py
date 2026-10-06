# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Helpers for using the `attr` library."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def attr_type(
    type_: Any,
    subname: str = '',
) -> Callable[[Any, Any, Any], None]:
  """An `attr.s` validator for asserting the type of a value.

  Essentially the same as `attr.validators.instance_of`, except that it allows
  the provision of a 'subname' to provide a better error message when checking
  a sub-field of the value.

  Args:
    * type_ (object) - The python type object to validate `value` against.
    * subname (str) - Some sub-element of attrib.name; e.g. if checking
      a dictionary key, this might be ' keys'.

  Returns a validator function which raises TypeError if the value doesn't match
  the value.
  """

  def inner(_self: Any, attrib: Any, value: Any) -> None:
    if not isinstance(value, type_):
      raise TypeError(
        "'{name}' must be {type!r} (got {value!r} that is a "
        "{actual!r}).".format(
          name=attrib.name+subname,
          type=type_,
          actual=value.__class__,
          value=value,
        ),
        attrib,
        value,
        type_,
        subname,
      )
  return inner


def attr_superclass(
    type_: Any,
    subname: str = '',
) -> Callable[[Any, Any, Any], None]:
  """An `attr.s` validator for asserting the superclass of a value.

  Args:
    * type_ (object) - The python type object to validate `value` is a subclass
      of.
    * subname (str) - Some sub-element of attrib.name; e.g. if checking
      a dictionary key, this might be ' keys'.

  Returns a validator function which raises TypeError if the value doesn't match
  the value.
  """

  def inner(_self: Any, attrib: Any, value: Any) -> None:
    if not issubclass(type(value), type_):
      raise TypeError(
        "'{name}' must be a subclass of {type!r} (got {value!r} that is a "
        "{actual!r}).".format(
          name=attrib.name+subname,
          type=type_,
          actual=value.__class__,
          value=value,
        ),
        attrib,
        value,
        type_,
        subname,
      )
  return inner


def attr_dict_type(
    key_type: Any,
    val_type: Any,
    value_seq: bool = False,
) -> Callable[[Any, Any, Any], None]:
  """Helper function for writing attr.s validators for dictionary types.

  Args:
    * key_type (object) - The python type object to validate the dict's keys.
    * val_type (object) - The python type object to validate the dict's
      values.
    * value_seq (bool) - If the dictionary maps to a sequence of val_type.

  Returns a validator function which raises TypeError if:
    * The value is not a dictionary
    * All of it's keys don't match `key_type`
    * All of it's values don't match `val_type`
  """

  def inner(self: Any, attrib: Any, value: Any) -> None:
    # late import to avoid import cycle
    from recipe_engine import engine_types

    attr_type((dict, engine_types.FrozenDict))(self, attrib, value)
    for k, subval in value.items():
      attr_type(key_type, ' keys')(self, attrib, k)
      subname = '[%r]' % k
      if value_seq:
        attr_seq_type(val_type, subname)(self, attrib, subval)
      else:
        attr_type(val_type, subname)(self, attrib, subval)

  return inner


def attr_seq_type(
    val_type: Any,
    subname: str = '',
) -> Callable[[Any, Any, Any], None]:
  """Helper function for writing attr.s validators for list types.

  Args:
    * val_type (object) - The python type object to validate the list's values.

  Returns a validator function which raises TypeError if:
    * The value is not a list, tuple, set or frozenset
    * All of it's values don't match `val_type`
  """

  def inner(self: Any, attrib: Any, value: Any) -> None:
    attr_type((list, tuple, set, frozenset), subname)(self, attrib, value)
    for subval in value:
      attr_type(val_type, subname + ' values')(self, attrib, subval)

  return inner


def attr_list_type(val_type: Any) -> Callable[[Any, Any, Any], None]:
  """Helper function for writing attr.s validators for list types.

  Args:
    * val_type (object) - The python type object to validate the list's values.

  Returns a validator function which raises TypeError if:
    * The value is not a list
    * All of it's values don't match `val_type`
  """

  def inner(self: Any, attrib: Any, value: Any) -> None:
    attr_type((list, tuple))(self, attrib, value)
    for subval in value:
      attr_type(val_type, ' values')(self, attrib, subval)

  return inner


def attr_value_is(
    msg: str,
    check_fn: Callable[[Any], bool],
    subname: str = '',
) -> Callable[[Any, Any, Any], None]:
  """Helper function for writing attr.s validators.

  Args:
    * msg (str) - The message to include in the ValueError. Should be
      the quoted part of: name is not '<msg>'.
    * check_fn (callable) - Called with 'value'; should return True iff the
      value is valid.
    * subname (str) - Some sub-element of attrib.name; e.g. if checking
      a dictionary key, this might be ' keys'.

  Returns a validator function which raises TypeError if the value doesn't match
  the value.
  """
  def inner(_self: Any, attrib: Any, value: Any) -> None:
    if not check_fn(value):
      raise ValueError(
        "'{name}' is not {msg} (got {value!r})".format(
          name=attrib.name+subname,
          msg=msg,
          value=value,
        ),
        attrib,
        value,
        msg,
        subname,
      )
  return inner
