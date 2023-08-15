# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""recipe_utils.py stores common utils to be shared between recipe_modules

Many recipes need common helper tasks such as validating parameters,
deleting files recursively without throwing exceptions, and other
miscellaneous tasks. Let's keep these utilities in one place so that
individual recipe_modules can do them consistently.

"""

from future.utils import iteritems
from typing import Any, Mapping, Sequence, TypeVar

T = TypeVar('T')


def check_type(name: str, var: T, expect: Any) -> T:
  """check_types checks that a variable has the expected type"""
  assert isinstance(name, str), f'name has bad type {type(name).__name__}'
  if not isinstance(var, expect):  # pragma: no cover
    if isinstance(expect, tuple):
      expect_type = ' or '.join('a ' + t.__name__ for t in expect)
    else:
      expect_type = 'a ' + expect.__name__
    raise TypeError('%s is not %s: %r (%s)' %
                    (name, expect_type, var, type(var).__name__))
  return var


def check_list_type(name: str, var: T, expect_inner: Any) -> T:
  """check_list_type checks that each element of a non-str sequence has the expected type"""
  assert isinstance(name, str), f'name has bad type {type(name).__name__}'
  if isinstance(var, (str, bytes)):  # pragma: no cover
    raise TypeError('%s must be a non-string sequence: %s (%r)' %
                    (name, type(var).__name__, var))
  # Allow all non-string sequences, not just tuple and list, because proto
  # object repeated fields use a special Sequence type.
  check_type(name, var, Sequence)
  for i, itm in enumerate(var):
    check_type('%s[%d]' % (name, i), itm, expect_inner)
  return var


def check_dict_type(name: str, var: T, expect_key: Any, expect_value: Any) -> T:
  """check_dict_type checks that each element of a dictionary has the expected type"""
  assert isinstance(name, str), f'name has bad type {type(name).__name__}'
  check_type(name, var, Mapping)
  for key, value in iteritems(var):
    check_type('%s: key' % name, key, expect_key)
    check_type('%s[%s]' % (name, key), value, expect_value)
  return var
