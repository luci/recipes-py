# Copyright 2026 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Util functions for query."""

import re

from PB.turboci.graph.orchestrator.v1.type_set import TypeSet
from PB.turboci.graph.orchestrator.v1.value_ref import ValueRef


def type_set_to_re(ts: TypeSet) -> re.Pattern:
  fragments: list[str] = []
  for frag in ts.type_urls:
    q = re.escape(frag)
    if q.endswith(r'\*'):
      fragments.append(q.removesuffix(r'\*') + '.*')
    else:
      fragments.append(q)

  return re.compile(f'({")|(".join(fragments)})')


def want_value_ref(pat: re.Pattern, value_ref: ValueRef) -> bool:
  return bool(pat.match(value_ref.type_url))
