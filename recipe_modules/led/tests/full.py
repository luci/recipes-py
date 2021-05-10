# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import re

from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.led.job import job
from PB.go.chromium.org.luci.swarming.proto.api import swarming
from PB.recipe_modules.recipe_engine.led.properties import InputProperties

DEPS = [
  'buildbucket',
  'led',
  'properties',
  'proto',
  'step',
]

PROPERTIES = {
  'child_properties': Property(default=None, kind=dict),
  'sloppy_child_properties': Property(default=None, kind=dict),
  'get_cmd': Property(default=None, kind=list),
  'do_bogus_edits': Property(default=False, kind=bool),
}


def RunSteps(api, get_cmd, child_properties, sloppy_child_properties, do_bogus_edits):
  intermediate = api.led(*get_cmd)
  intermediate = intermediate.then(
      'edit-cr-cl', 'https://fake.url/c/project/123/+/456')

  # add another cl
  intermediate = intermediate.then(
      'edit-cr-cl', '-no-implicit-clear',
      'https://fake.url/c/project/other/+/19/2')

  # remove the first one (1337 is the default mock patchset)
  intermediate = intermediate.then(
      'edit-cr-cl', '-remove',
      'https://fake.url/c/project/123/+/456/1337')

  # Only use a different version of the recipes code if this is a led job.
  if api.led.launched_by_led:
    assert api.led.run_id
    intermediate = api.led.inject_input_recipes(intermediate)

  if child_properties:
    edit_args = ['edit']
    for k, v in child_properties.items():
      edit_args.extend(['-p', '%s=\"%s\"' % (k, v)])
    for k, v in sloppy_child_properties.items():
      edit_args.extend(['-pa', '%s=%s' % (k, v)])
    intermediate = intermediate.then(*edit_args)

  if do_bogus_edits:
    intermediate = intermediate.then('edit', '-bogus', 'bogus_arg_value')
    intermediate = intermediate.then('edit', '--bogus', 'double_bogus')
    intermediate = intermediate.then('edit', '--bogus=triple_bogus')

  intermediate = intermediate.then('edit', '-name', 'foobar')

  intermediate = intermediate.then('edit-recipe-bundle')

  api.step('print pre-launch', [
      'echo', api.proto.encode(intermediate.result, 'JSONPB')])

  api.step('print rbh value', ['echo', intermediate.edit_rbh_value])

  final_result = intermediate.then('launch')
  api.step('print task id', [
      'echo', final_result.launch_result.task_id])


def GenTests(api):
  def led_props(input_properties):
    return api.properties(**{'$recipe_engine/led': input_properties})

  yield (
      api.test('basic') +
      api.properties(get_cmd=['get-builder', 'chromium/try:linux-rel'])
  )

  mock_build = job.Definition()
  mock_build.buildbucket.name = "hi, get-builder"
  yield (
      api.test('old bucket syntax') +
      api.properties(get_cmd=['get-builder', 'luci.chromium.try:linux-rel']) +
      api.led.mock_get_builder(mock_build, 'chromium', 'try', 'linux-rel')
  )

  mock_build = job.Definition()
  mock_build.buildbucket.name = "hi, get-build"
  yield (
      api.test('get-build') +
      api.properties(get_cmd=['get-build', '123456789']) +
      api.led.mock_get_build(mock_build, 123456789)
  )

  def _apply_always(build, cmd, cwd):
    '''Applies on every edit invocation.'''
    build.buildbucket.name += " always"

  def _apply_builder(build, cmd, cwd):
    '''Applies on every edit invocation targeting the builder.'''
    build.buildbucket.name += " builder"

  def _apply_never(build, cmd, cwd):
    assert False # pragma: no cover

  def _apply_bogus_arg(build, cmd, cwd):
    '''Applies only on edit invocations with the -bogus arg.'''
    vals = api.led.get_arg_values(cmd, 'bogus')
    assert len(vals) == 1
    assert 'bogus' in vals[0]
    build.buildbucket.name += " " + vals[0]

  def _stop_application(build, cmd, cwd):
    return api.led.StopApplyingMocks

  yield (
      api.test('edit mock') +
      api.properties(
          get_cmd=['get-builder', 'luci.chromium.try:linux-rel'],
          do_bogus_edits=True,
      ) +
      api.led.mock_edit(_apply_always) +
      api.led.mock_edit(_apply_builder,
                        build_id='buildbucket/builder/chromium/try/linux-rel') +
      api.led.mock_edit(_apply_never,
                        build_id='buildbucket/builder/nope/nope/nope') +
      api.led.mock_edit(_apply_bogus_arg, cmd_filter=[
        # A real user of this test would probably not use this regex since
        # they'd control the argument. Alternately they'd always apply
        # _apply_bogus_arg and just have it do nothing if the '-bogus' flag
        # wasn't present.
        'edit', Ellipsis, re.compile('--?bogus(=.*)?'),
      ]) +
      api.led.mock_edit(_apply_never, cmd_filter=[
        'edit', Ellipsis, '-walrus',
      ]) +
      api.led.mock_edit(_stop_application) +
      api.led.mock_edit(_apply_never)
  )

  mock_build = job.Definition()
  mock_build.buildbucket.name = "hi, get-swarm"
  yield (
      api.test('get-swarm') +
      api.properties(get_cmd=['get-swarm', 'deadbeef']) +
      api.led.mock_get_swarm(mock_build, 'deadbeef')
  )

  isolated_hash = 'somehash123'
  led_run_id = 'led/user_example.com/deadbeef'
  yield (
      api.test('with-isolated-input') +
      api.properties(get_cmd=['get-builder', 'chromium/try:linux-rel']) +
      led_props(InputProperties(
          led_run_id=led_run_id,
          isolated_input=InputProperties.IsolatedInput(
              hash=isolated_hash,
              namespace='default-gzip',
              server='isolateserver.appspot.com',
          ),
      ))
  )

  yield (
      api.test('with-rbe-cas-input') +
      api.properties(get_cmd=['get-builder', 'chromium/try:linux-rel']) +
      led_props(InputProperties(
          led_run_id=led_run_id,
          rbe_cas_input=swarming.CASReference(
              cas_instance='projects/example/instances/default_instance',
              digest=swarming.Digest(
                  hash='examplehash',
                  size_bytes=71,
              ),
          ),
      ))
  )

  cipd_source = common.Executable(
      cipd_package='recipe_dir/recipes',
      cipd_version='refs/heads/main',
  )
  yield (
      api.test('with-cipd-input') +
      api.properties(get_cmd=['get-builder', 'chromium/try:linux-rel']) +
      led_props(InputProperties(
          led_run_id=led_run_id,
          cipd_input=InputProperties.CIPDInput(
              package=cipd_source.cipd_package,
              version=cipd_source.cipd_version,
          ),
      ))
  )

  yield (
      api.test('edit-properties') +
      api.properties(get_cmd=['get-builder', 'chromium/try:linux-rel']) +
      api.properties(child_properties={'prop': 'val'}) +
      api.properties(sloppy_child_properties={'sloppy': 'val'}) +
      led_props(InputProperties(led_run_id=led_run_id)))
