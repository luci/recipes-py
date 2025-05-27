# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for lookup_bug."""

from __future__ import annotations

DEPS = [
    'luci_analysis',
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/step',
]


def RunSteps(api):
  with api.step.nest('nest_parent') as presentation:
    bug = 'chromium/123'
    rules = api.luci_analysis.lookup_bug(bug)
    presentation.logs['rules'] = api.json.dumps(rules)


from recipe_engine import post_process


def GenTests(api):
  yield api.test(
      'base',
      api.luci_analysis.lookup_bug([
          'projects/chromium/rules/00000000000000000000ffffffffffff',
      ],
                                   'chromium/123',
                                   parent_step_name='nest_parent'),
      api.post_check(lambda check, steps: check(
          api.json.loads(steps['nest_parent'].logs['rules']) == [
              'projects/chromium/rules/00000000000000000000ffffffffffff',
          ])),
      api.post_process(post_process.DropExpectation),
  )
