# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Temporarily houses everything that will be gone with annotation protocol.

TODO(yiwzhang): Delete the module after recipe engine is fully on luciexe mode
"""

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb
from PB.recipe_engine import result as result_pb


def to_legacy_result(
    result: result_pb.RawResult | None,
) -> result_pb.Result | None:
  """Convert from result_pb.RawResult to result_pb.Result."""
  if not result:
    return None
  legacy_result = result_pb.Result()
  if result.status != common_pb.SUCCESS:
    legacy_result.failure.human_reason = result.summary_markdown
    if result.status not in (common_pb.INFRA_FAILURE, common_pb.CANCELED):
      legacy_result.failure.failure.SetInParent()
  return legacy_result