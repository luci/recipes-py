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
    TransactionConflictException,
    TransactionUseAfterWriteException,
    TurboCIException,
)

__all__ = [
    'check',
    'check_id',
    'CheckWriteInvariantException',
    'collect_check_ids',
    'edge_group',
    'from_id',
    'make_query',
    'query_nodes',
    'read_checks',
    'reason',
    'to_id',
    'TransactionConflictException',
    'TransactionUseAfterWriteException',
    'TurboCIException',
    'type_url_for',
    'type_urls',
    'wrap_id',
    'write_nodes',
]
