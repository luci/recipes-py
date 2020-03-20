# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Proto-free, forzen version of Cause related messages in warning.proto

These data class can adapt from/to protobuf message input/output and be used
as intermidate data model in recipe engine since they provide natural hashing
ability for deduplication.
"""

import os
import inspect

import attr

from PB.recipe_engine import warning as warning_pb

from ..attr_util import attr_type, attr_value_is, attr_list_type
from ...types import freeze

@attr.s(frozen=True)
class Frame(object):
  """Equivalent to warning_pb.Frame."""
  # Absolute file path that contains the code object  frame is executing.
  file = attr.ib(validator=[
    attr_type(str),
    attr_value_is('an absolute path', os.path.isabs),
  ])

  # Current line Number in the source code for the frame.
  line = attr.ib(validator=attr_type(int))

  @classmethod
  def from_built_in_frame(cls, frame):
    """Create a new instance from built-in frame object."""
    assert inspect.isframe(frame), 'Expect FrameType; Got %s' % type(frame)
    return cls(
      file=frame.f_code.co_filename,
      line=int(frame.f_lineno),
    )

  def to_frame_pb(self):
    """Create a warning_pb.Frame message instance"""
    return warning_pb.Frame(file=self.file, line=self.line)

@attr.s(frozen=True)
class CallSite(object):
  """Equivalent to warning_pb.CallSite."""
  # The frame of the call site
  site = attr.ib(validator=attr_type(Frame))
  # The call stack at the time warning is issued (optional)
  call_stack = attr.ib(
    converter=freeze,
    validator=attr_list_type(Frame),
    default=tuple(),
  )

  def to_cause_pb(self):
    """Create a warning_pb.Cause message instance"""
    ret = warning_pb.Cause()
    ret.call_site.site.CopyFrom(self.site.to_frame_pb())
    for frame in self.call_stack:
      ret.call_site.call_stack.add().CopyFrom(frame.to_frame_pb())
    return ret

@attr.s(frozen=True)
class ImportSite(object):
  """Equivalent to warning_pb.ImportSite"""
  # Repo that recipe or recipe module is in
  repo = attr.ib(validator=attr_type(str))
  # Name of recipe module
  module = attr.ib(validator=attr.validators.optional(attr_type(str)))
  # Name of recipe
  recipe = attr.ib(validator=attr.validators.optional(attr_type(str)))

  def __attrs_post_init__(self):
    """ Check one of recipe or recipe module should present"""
    if bool(self.module) == bool(self.recipe):
      raise ValueError(
        'Expect one of recipe or module presents. '
        'Got module:%s, recipe:%s' % (self.module, self.recipe))

  def to_cause_pb(self):
    """Create a warning_pb.Cause message instance"""
    ret = warning_pb.Cause()
    ret.import_site.repo = self.repo
    if self.module:
      ret.import_site.module = self.module
    else:
      ret.import_site.recipe = self.recipe
    return ret


