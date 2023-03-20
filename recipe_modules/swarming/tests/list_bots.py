# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process
from RECIPE_MODULES.recipe_engine.swarming.api import LIST_BOTS_MANDATORY_FIELDS

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'assertions',
    'swarming',
]


def RunSteps(api):
  # list_bots from test_api returns 3 bots which is dead, quarantined,
  # and alive respectively.
  bots = api.swarming.list_bots(
      'List Bots', dimensions={'os': 'Android'}, fields=['items/external_ip'])
  api.assertions.assertEqual(len(bots), 3)

  bot_dead = bots[0]
  api.assertions.assertTrue(bot_dead.is_dead)
  api.assertions.assertEqual(bot_dead.dimensions.get('os'), 'Android')

  bot_quarantined = bots[1]
  api.assertions.assertTrue(bot_quarantined.quarantined)
  api.assertions.assertEqual(bot_quarantined.dimensions.get('os'), 'Android')

  bot_alive = bots[2]
  api.assertions.assertFalse(bot_alive.is_dead)
  api.assertions.assertFalse(bot_alive.quarantined)
  api.assertions.assertEqual(bot_alive.dimensions.get('os'), 'Android')
  api.assertions.assertIn(bot_alive.bot_id, bot_alive.bot_ui_link)
  api.assertions.assertIsNotNone(bot_alive.state)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.StepCommandContains, 'List Bots',
                       ['-dimension', 'os=Android']),
      api.post_process(post_process.StepCommandContains, 'List Bots',
                       ['-field', LIST_BOTS_MANDATORY_FIELDS]),
      api.post_process(post_process.StepCommandContains, 'List Bots',
                       ['-field', 'items/external_ip']),
      api.post_process(post_process.DropExpectation),
  )
