# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""The turboci module implements a client for the TurboCI service whose
API protos are at:

  https://chromium.googlesource.com/infra/turboci/proto

Usage:

    from recipe_engine import turboci

    def RunSteps(...):
      turboci.query_nodes(...)
      turboci.write_nodes(...)

    def GenTests(...):
      api.test(
        'name',
        # TBD: Testing API to assert graph state after recipe ends.
      )
"""

from .internal.turboci.ids import (
    from_id,
    to_id,
    type_url_for,
    type_urls,
    wrap_id,
)

from .internal.turboci.common import (
    TurboCIClient,
    check,
    check_id,
    collect_check_ids,
    edge_group,
    make_query,
    query_nodes,
    read_checks,
    reason,
    write_nodes,
)

from .internal.turboci.errors import (
    CheckWriteInvariantException,
    InvalidArgumentException,
    TransactionConflictException,
    TransactionUseAfterWriteException,
    TurboCIException,
)

from .internal.turboci.transaction import (
    Transaction,
    run_transaction,
)

from recipe_engine.internal.turboci import common as _common

def get_client() -> TurboCIClient:
  """Gets the current raw client interface."""
  return _common.CLIENT

__all__ = [
    'check',
    'check_id',
    'CheckWriteInvariantException',
    'collect_check_ids',
    'edge_group',
    'from_id',
    'get_client',
    'InvalidArgumentException',
    'make_query',
    'query_nodes',
    'read_checks',
    'reason',
    'run_transaction',
    'to_id',
    'Transaction',
    'TransactionConflictException',
    'TransactionUseAfterWriteException',
    'TurboCIException',
    'type_url_for',
    'type_urls',
    'wrap_id',
    'write_nodes',
]
