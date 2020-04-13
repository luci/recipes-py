# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Temporarily houses everything that will be gone with annotation protocol.

TODO(yiwzhang): Delete the module after recipe engine is fully on luciexe mode
"""

from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

def to_legacy_result(result):
  """Convert from result_pb2.RawResult to result_pb2.Result."""
  if not result:
    return None
  legacy_result = result_pb2.Result()
  if result.status != common_pb2.SUCCESS:
    legacy_result.failure.human_reason = result.summary_markdown
    if result.status != common_pb2.INFRA_FAILURE:
      legacy_result.failure.failure.SetInParent()
  return legacy_result