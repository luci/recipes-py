# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contains helpers for TurboCI TypeSet and TypeInfo messages."""

from __future__ import annotations

import bisect
import dataclasses
import enum
import typing

from google.protobuf import message
from PB.turboci.graph.orchestrator.v1 import type_info as type_info_pb2
from PB.turboci.graph.orchestrator.v1 import type_set as type_set_pb2
from turboci.utils import value

__all__ = [
    'ALL_TYPES',
    'TypeSet',
    'TypeInfo',
]

ALL_TYPES = '*'


class TypeSet:
  """A parsed version of a TurboCI TypeSet proto."""

  def __init__(
      self,
      patterns: typing.Sequence[
          type[message.Message] | message.Message | str
      ] = (),
  ):
    """Creates a new TypeSet with the provided patterns.

    Message classes (or message instances) will be converted to an exact-match
    pattern for that specific protobuf message (using `value.url`).

    Including ALL_TYPES will cause the resulting TypeSet to match all protobuf
    types.

    Raises ValueError if any of the patterns are malformed.
    """
    if not patterns:
      self._patterns: list[str] = []
      return

    all_patterns = sorted(
        x if isinstance(x, str) else value.url(x) for x in patterns
    )
    prev = all_patterns[0]
    self._validate_pattern(prev)
    fixed = [prev]
    for pat in all_patterns[1:]:
      self._validate_pattern(pat)
      if pat == prev or self._is_matching_pattern(prev, pat):
        continue
      fixed.append(pat)
      prev = pat

    self._patterns = fixed

  @staticmethod
  def from_proto(pb: type_set_pb2.TypeSet) -> TypeSet:
    """Constructs a new TypeSet from its protobuf counterpart."""
    return TypeSet(pb.type_urls)

  def to_proto(self) -> type_set_pb2.TypeSet:
    """Returns this TypeSet as its protobuf counterpart."""
    return type_set_pb2.TypeSet(type_urls=self._patterns)

  def matches(self, type_url: str) -> bool:
    """Returns true if this TypeSet matches `type_url`."""
    if not self._patterns:
      return False

    idx = bisect.bisect_left(self._patterns, type_url)
    if idx < len(self._patterns):
      if self._patterns[idx] == type_url:
        # exact match
        return True

    if idx == 0:
      # No preceding pattern which could match type_url.
      return False

    return self._is_matching_pattern(self._patterns[idx - 1], type_url)

  @staticmethod
  def _is_matching_pattern(pattern: str, type_url: str) -> bool:
    last = len(pattern) - 1
    return pattern[last] == '*' and type_url.startswith(pattern[:last])

  @staticmethod
  def _validate_pattern(pattern: str) -> None:
    if pattern == ALL_TYPES:
      return

    if not pattern.startswith(value.TYPE_URL_PREFIX):
      raise ValueError(f'pattern does not start with {value.TYPE_URL_PREFIX!r}')

    has_suffix_pattern = pattern.endswith(('.*', '/*'))
    if has_suffix_pattern:
      # trim off the trailing *
      pattern = pattern.rstrip('*')

    if '*' in pattern:
      if has_suffix_pattern:
        raise ValueError('pattern contains multiple `*`')
      raise ValueError(
          'pattern has bad `*`: only allowed as suffix after `.` or `/`'
      )


@dataclasses.dataclass
class TypeInfo:
  """A parsed version of a TurboCI TypeSet proto."""

  class Wanted(enum.Enum):
    """Indicator of how a given type_url is wanted by the TypeInfo.

    Returned by TypeInfo.wants.
    """

    BINARY = 1
    JSON = 2

  # The set of types that you want to get back from the TurboCI service.
  wanted: TypeSet = dataclasses.field(default_factory=TypeSet)

  # If True, ask the service to encode `wanted` types not matching `known` as
  # JSONPB.
  unknown_jsonpb: bool = False

  # If `unknown_jsonpb` is True, then types matching both `wanted` and `known`
  # will be returned as binary proto.
  known: TypeSet = dataclasses.field(default_factory=TypeSet)

  @staticmethod
  def from_proto(pb: type_info_pb2.TypeInfo) -> TypeInfo:
    """Constructs a new TypeInfo from its protobuf counterpart."""
    return TypeInfo(
        wanted=TypeSet.from_proto(pb.wanted),
        unknown_jsonpb=pb.unknown_jsonpb,
        known=TypeSet.from_proto(pb.known),
    )

  def to_proto(self) -> type_info_pb2.TypeInfo:
    """Returns this TypeInfo as its protobuf counterpart."""
    return type_info_pb2.TypeInfo(
        wanted=self.wanted.to_proto(),
        unknown_jsonpb=self.unknown_jsonpb,
        known=self.known.to_proto(),
    )

  def wants(self, type_url: str) -> None | Wanted:
    """Does the TypeInfo want this type_url?

    None means that the TypeInfo does not want the type_url.

    Otherwise `Wanted` indicates if it's wanted as BINARY or as JSON data.
    """
    if not self.wanted.matches(type_url):
      return None
    if not self.unknown_jsonpb:
      return self.Wanted.BINARY
    return (
        self.Wanted.BINARY if self.known.matches(type_url) else self.Wanted.JSON
    )
