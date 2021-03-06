# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'cq',
  'properties',
  'step',
]


def RunSteps(api):
  api.step('show properties', [])
  api.step.active_result.presentation.logs['result'] = [
    'state: %s' % (api.cq.state,),
  ]


def GenTests(api):
  yield api.test('inactive') + api.cq()
  yield api.test('dry') + api.cq(dry_run=True)
  yield api.test('full') + api.cq(full_run=True)
  yield api.test('legacy-full') + api.properties(**{
    '$recipe_engine/cq': {'dry_run': False},
  })
  yield api.test('legacy-dry') + api.properties(**{
    '$recipe_engine/cq': {'dry_run': True},
  })
