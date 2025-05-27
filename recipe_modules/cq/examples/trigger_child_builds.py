# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process, recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
  'assertions',
  'buildbucket',
  'cq',
  'json',
  'properties',
  'step',
]


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api):
  properties = {'foo': 'bar'}
  properties.update(api.cq.props_for_child_build)
  req = api.buildbucket.schedule_request(
      builder='child',
      gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),
      properties=properties)
  child_builds = api.buildbucket.schedule([req])
  api.cq.record_triggered_builds(*child_builds)


def GenTests(api):
  def check_has_bb_tag(check, steps, key, value):
    req = api.json.loads(steps['buildbucket.schedule'].logs['request'])
    tags = req['requests'][0]['scheduleBuild'].get('tags', [])
    check({'key': key, 'value': value} in tags)

  def extract_cq_props(steps):
    req = api.json.loads(steps['buildbucket.schedule'].logs['request'])
    return req['requests'][0]['scheduleBuild'].get('properties', {}).get(
        '$recipe_engine/cq', {})

  def check_set_to(check, steps, key, value):
    props = extract_cq_props(steps)
    check(props[key] == value)

  def check_unset(check, steps, key):
    props = extract_cq_props(steps)
    check(key not in props)

  yield (
    api.test('typical')
    + api.buildbucket.try_build()
    + api.cq(run_mode=api.cq.FULL_RUN)
    + api.post_check(check_set_to, 'active', True)
    + api.post_check(check_set_to, 'run_mode', 'FULL_RUN')
    + api.post_check(check_unset, 'top_level')
    + api.post_process(post_process.DropExpectation)
  )
  yield (api.test('grand-child')
         # Unfortunate coupling: experimental means special tag, too.
         + api.buildbucket.try_build(
             tags=api.buildbucket.tags(cq_experimental='true')) +
         api.cq(run_mode=api.cq.DRY_RUN, top_level=False, experimental=True) +
         api.post_check(check_set_to, 'active', True) +
         api.post_check(check_set_to, 'run_mode', 'DRY_RUN') +
         api.post_check(check_set_to, 'experimental', True) +
         api.post_check(check_has_bb_tag, 'cq_experimental', 'true') +
         api.post_check(check_unset, 'top_level') +
         api.post_process(post_process.DropExpectation))
  yield (
    api.test('not-a-cq-run')
    + api.post_check(check_unset, 'active')
    + api.post_process(post_process.DropExpectation)
  )
