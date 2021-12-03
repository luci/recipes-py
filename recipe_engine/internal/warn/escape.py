# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides functionalities to selectively escape functions from warnings.

Example usage:
  1. escape function `foo` from warnings have prefix 'BAR1_'or 'BAR2_'
    @escape_warnings('^BAR1_.*$', '^BAR2_.*$')
    def foo():
      pass
  2. escape function `foo` from all warnings
    @escape_all_warnings
    def foo():
      pass
"""

import os
import re

import attr

from ..attr_util import attr_type

@attr.s(frozen=True, slots=True)
class FuncLoc(object):
  """An immutable class that describes the location of a function."""
  # Absolute path to the file containing this function's source
  file_path = attr.ib(validator=attr_type(str), converter=os.path.abspath)
  # First line number of this function
  first_line_no = attr.ib(validator=attr_type(int))

  @classmethod
  def from_code_obj(cls, code_obj):
    """Create a new instance from the given code object."""
    return cls(code_obj.co_filename, code_obj.co_firstlineno)


# Shared global variable that persists the mapping between the function and the
# regular expression patterns that if one of them matches the issued warning,
# warning will be attributed to the caller of this function instead
# Dict[FuncLoc, Tuple[regular expression pattern]]
WARNING_ESCAPE_REGISTRY = {}

# Similar to WARNING_ESCAPE_REGISTRY except contains patterns for ignoring
# warnings.
WARNING_IGNORE_REGISTRY = {}

# Special object returned by escape_warning_predicate when a warning should be
# completely ignored.
IGNORE = object()

def escape_warning_predicate(name, frame):
  """A predicate used in warning recorder that returns True when the function
  that the given frame is currently executing is escaped from the given warning
  name via decorators provided in this module.
  """
  func_loc = FuncLoc.from_code_obj(frame.f_code)
  if any(r.match(name) for r in WARNING_IGNORE_REGISTRY.get(func_loc, tuple())):
    return IGNORE
  if any(r.match(name) for r in WARNING_ESCAPE_REGISTRY.get(func_loc, tuple())):
    return 'escaped function at %s#L%d' % (
      func_loc.file_path, func_loc.first_line_no)
  return None

def escape_warnings(*warning_name_regexps):
  """A function decorator which will cause warnings matching any of the given
  regexps to be attributed to the decorated function's caller instead of the
  decorated function itself.
  """
  def _escape_warnings(func):
    func_loc = FuncLoc.from_code_obj(func.__code__)
    WARNING_ESCAPE_REGISTRY[func_loc] = (
      tuple(re.compile(r) for r in warning_name_regexps))
    return func
  return _escape_warnings

def escape_all_warnings(func):
  """Shorthand decorator to escape the decorated function from all warnings."""
  return escape_warnings('.*')(func)

def ignore_warnings(*warning_name_regexps):
  """A function decorator which will cause warnings matching any of the given
  regexps to be ignored.
  """
  def _escape_warnings(func):
    func_loc = FuncLoc.from_code_obj(func.__code__)
    WARNING_IGNORE_REGISTRY[func_loc] = (
      tuple(re.compile(r) for r in warning_name_regexps))
    return func
  return _escape_warnings
