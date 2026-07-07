# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helpers for matching ValueRefs and ValueWrites."""

from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from PB.turboci.graph.orchestrator.v1 import value_write as value_write_pb2
from turboci.utils.value import digest


def write_matches_ref(
    write: value_write_pb2.ValueWrite, ref: value_ref_pb2.ValueRef
) -> bool:
  """Returns True if `write` realm and content matches `ref`'s."""
  if write.realm != ref.realm or write.data.type_url != ref.type_url:
    return False

  if not ref.HasField('digest'):
    # ref is invalid as it doesn't have digest set
    return False

  return ref.digest == str(digest.Digest.compute(write.data))


def ref_matches_ref(
    a: value_ref_pb2.ValueRef, b: value_ref_pb2.ValueRef
) -> bool:
  """Returns True if `a` and `b` have the same realm and content."""
  if a.realm != b.realm or a.type_url != b.type_url:
    return False

  if not a.HasField('digest') or not b.HasField('digest'):
    # one of the refs is invalid as it doesn't have digest set
    return False

  return a.digest == b.digest
