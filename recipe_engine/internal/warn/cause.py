# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Proto-free, frozen version of Cause related messages in warning.proto.

These data classes can adapt from/to protobuf message and be used as intermidate
data model in recipe engine as they provide natural hashing ability for fast
deduplication.
"""

from __future__ import annotations

from collections.abc import Sequence
import functools
import inspect
import os
import types
from typing import Any

import attr

from ... import engine_types
from .. import attr_util


@attr.s(frozen=True)
class Frame:
  """Equivalent to warning_pb.Frame."""
  # Absolute file path that contains the code object frame is executing.
  file: str = attr.ib(
    validator=[
      attr_util.attr_type(str),
      attr_util.attr_value_is('an absolute path or empty string',
                              lambda val: os.path.isabs(val) or val == ''),
    ],
    default='',
  )

  # Current line Number in the source code for the frame.
  line: int = attr.ib(validator=attr_util.attr_type(int), default=0)

  @functools.cached_property
  def frame_pb(self) -> Any:
    """The equivalent warning_pb.Frame proto message instance"""
    from PB.recipe_engine import warning as warning_pb

    return warning_pb.Frame(file=self.file, line=self.line)

  @classmethod
  def from_frame_pb(cls, frame: Any) -> Frame:
    """Create a new instance from a warning_pb.Frame proto message."""
    return cls(file=str(frame.file), line=frame.line)

  @classmethod
  def from_built_in_frame(cls, frame: types.FrameType) -> Frame:
    """Create a new instance from built-in frame object."""
    assert inspect.isframe(frame), 'Expect FrameType; Got %s' % type(frame)
    return cls(
      file=os.path.abspath(frame.f_code.co_filename),
      line=int(frame.f_lineno),
    )


@attr.s(frozen=True)
class CallSite:
  """Equivalent to warning_pb.CallSite."""
  # The frame of the call site. The frame will have empty value for all its
  # attributes if call site can't be attributed.
  site: Frame = attr.ib(validator=attr_util.attr_type(Frame))
  # The call stack at the time warning is issued (optional)
  call_stack: Sequence[Frame] = attr.ib(
    converter=engine_types.freeze,
    validator=attr_util.attr_list_type(Frame),
    default=tuple(),
  )

  @functools.cached_property
  def cause_pb(self) -> Any:
    """The equivalent warning_pb.Cause proto message instance"""
    from PB.recipe_engine import warning as warning_pb

    ret = warning_pb.Cause()
    ret.call_site.site.CopyFrom(self.site.frame_pb)
    for f in self.call_stack:
      ret.call_site.call_stack.add().CopyFrom(f.frame_pb)
    return ret

  @classmethod
  def from_cause_pb(cls, cause: Any) -> CallSite:
    """Create a new instance from a warning_pb.Cause proto message."""
    return cls(
        site=Frame.from_frame_pb(cause.call_site.site),
        call_stack=[
            Frame.from_frame_pb(f) for f in cause.call_site.call_stack],
    )


@attr.s(frozen=True)
class ImportSite:
  """Equivalent to warning_pb.ImportSite"""
  # Name of the repo that recipe or recipe module is in
  repo: str = attr.ib(validator=attr_util.attr_type(str))
  # Name of recipe module
  module: str | None = attr.ib(
      validator=attr.validators.optional(attr_util.attr_type(str)))
  # Name of recipe
  recipe: str | None = attr.ib(
      validator=attr.validators.optional(attr_util.attr_type(str)))

  def __attrs_post_init__(self) -> None:
    """Check that exactly one of recipe or recipe module is present"""
    if bool(self.module) == bool(self.recipe):
      raise ValueError(
        'Expect exactly one of recipe or recipe module presents. '
        'Got module:%s, recipe:%s' % (self.module, self.recipe))

  @functools.cached_property
  def cause_pb(self) -> Any:
    """The equivalent warning_pb.Cause proto message instance"""
    from PB.recipe_engine import warning as warning_pb

    ret = warning_pb.Cause()
    ret.import_site.repo = self.repo
    if self.module:
      ret.import_site.module = self.module
    else:
      ret.import_site.recipe = self.recipe
    return ret

  @classmethod
  def from_cause_pb(cls, cause: Any) -> ImportSite:
    """Create a new instance from a warning_pb.Cause proto message."""
    import_site = cause.import_site
    return cls(
        repo=str(import_site.repo),
        module=str(import_site.module) if import_site.module else None,
        recipe=str(import_site.recipe) if import_site.recipe else None,
    )
