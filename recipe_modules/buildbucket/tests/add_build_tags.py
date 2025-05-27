# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'buildbucket',
  'step',
]


def RunSteps(api):
  tags = api.buildbucket.tags(k1='v1', k2=['v2', 'v2_1'])
  api.buildbucket.add_tags_to_current_build(tags)
  api.buildbucket.hide_current_build_in_gerrit()

def GenTests(api):
  yield api.test('basic')
