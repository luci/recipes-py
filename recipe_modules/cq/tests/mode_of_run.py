# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api

DEPS = [
  'cq',
  'properties',
  'step',
]


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api):
  api.step('show properties', [])
  api.step.active_result.presentation.logs['result'] = [
    'mode: %s' % (api.cq.run_mode,),
  ]


def GenTests(api):
  yield api.test('dry') + api.cq(run_mode=api.cq.DRY_RUN)
  yield api.test('quick-dry') + api.cq(run_mode=api.cq.QUICK_DRY_RUN)
  yield api.test('full') + api.cq(run_mode=api.cq.FULL_RUN)
  yield api.test('legacy-full') + api.properties(**{
    '$recipe_engine/cq': {'dry_run': False},
  })
  yield api.test('legacy-dry') + api.properties(**{
    '$recipe_engine/cq': {'dry_run': True},
  })
