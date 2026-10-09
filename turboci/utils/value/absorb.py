# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helper for writing tests which want to populate DataSource."""

__all__ = [
    'absorb_inline',
]

from PB.turboci.graph.orchestrator.v1 import value_data as value_data_pb2
from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from turboci.utils.value import data_source
from turboci.utils.value import digest


def absorb_inline(
    ds: data_source.MutableDataSource, ref: value_ref_pb2.ValueRef
) -> None:
  """Consumes the inline data in `ref` into `ds`.

  Mutates `ref` to ensure the corresponding `digest` is populated.

  No-op to absorb refs which have no inline data.
  """
  if not ref.HasField('inline'):
    return

  dgst = digest.Digest.compute(ref.inline)
  ds[str(dgst)] = value_data_pb2.ValueData(binary=ref.inline)
  ref.digest = dgst
  ref.ClearField('inline')
