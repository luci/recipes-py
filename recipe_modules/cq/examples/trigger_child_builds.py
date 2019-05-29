# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
  'assertions',
  'buildbucket',
  'cq',
  'json',
  'properties',
  'step',
]


def RunSteps(api):
  properties = {'foo': 'bar'}
  properties.update(api.cq.props_for_child_build)
  req = api.buildbucket.schedule_request(
      builder='child',
      tags=api.buildbucket.tags(**api.buildbucket.tags_for_child_build),
      gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),
      properties=properties)
  child_builds = api.buildbucket.schedule([req])
  api.cq.record_triggered_builds(*child_builds)


def GenTests(api):
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
    + api.cq(full_run=True)
    + api.post_check(check_set_to, 'active', True)
    + api.post_check(check_unset, 'dry_run')
    + api.post_check(check_unset, 'top_level')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('grand-child')
    + api.cq(dry_run=True, top_level=False, experimental=True)
    + api.post_check(check_set_to, 'active', True)
    + api.post_check(check_set_to, 'dry_run', True)
    + api.post_check(check_set_to, 'experimental', True)
    + api.post_check(check_unset, 'top_level')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('not-a-cq-run')
    + api.post_check(check_unset, 'active')
    + api.post_process(post_process.DropExpectation)
  )
