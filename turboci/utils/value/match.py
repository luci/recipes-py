# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helpers for matching ValueRefs and ValueWrites."""

from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from PB.turboci.graph.orchestrator.v1 import value_write as value_write_pb2
from turboci.utils.value import digest


def write_matches_ref(
    write: value_write_pb2.ValueWrite,
    ref: value_ref_pb2.ValueRef,
    *,
    match_tags: bool = True,
) -> bool:
  """Returns True if `write` realm and content (including tags) matches `ref`'s.

  `ref` must have a digest.

  If `ref` has both `inline` and `digest`, it is the caller's responsibility
  to ensure these match.
  """
  if write.realm != ref.realm or write.data.type_url != ref.type_url:
    return False

  if not ref.HasField('digest'):
    # ref is invalid as it doesn't have digest set
    return False

  # If the ref happens to have `inline` set, directly compare it.
  if ref.HasField('inline'):
    data_matches = write.data == ref.inline
  else:
    # Otherwise, compute the digest of the data and compare it to the ref
    # digest.
    data_matches = digest.Digest.compute(write.data) == ref.digest

  if not data_matches or not match_tags:
    return data_matches

  return write.tags == ref.tags


def ref_matches_ref(
    a: value_ref_pb2.ValueRef,
    b: value_ref_pb2.ValueRef,
    *,
    match_tags: bool = True,
) -> bool:
  """Returns True if `a` and `b` have the same realm and content.

  This includes tags.

  If the refs have `inline` data, it is the caller's responsibility to ensure
  these match the digests.
  """
  if a.realm != b.realm or a.type_url != b.type_url:
    return False

  if not a.HasField('digest') or not b.HasField('digest'):
    # one of the refs is invalid as it doesn't have digest set
    return False

  data_matches = a.digest == b.digest
  if not data_matches or not match_tags:
    return data_matches

  return a.tags == b.tags
