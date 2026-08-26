# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.led.properties import InputProperties as LedInputProperties
from PB.recipe_modules.recipe_engine.led.tests import led_real_build as led_real_build_pb
from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    led,
    properties,
    proto,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  led: led.API
  properties: properties.API
  proto: proto.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  repeated string get_cmd = 1;
}
"""

PROPERTIES = led_real_build_pb.InputProperties


def RunSteps(api: DEPS, props: led_real_build_pb.InputProperties):
  intermediate = api.led(*props.get_cmd)

  if api.led.launched_by_led:
    assert api.led.shadowed_bucket

  intermediate = intermediate.then(
      'edit-gerrit-cl', 'https://fake.url/c/project/123/+/456')

  intermediate = intermediate.then('edit', '-name', 'foobar')

  intermediate = intermediate.then('edit-recipe-bundle')

  api.step('print pre-launch', [
      'echo', api.proto.encode(intermediate.result, 'JSONPB')])

  api.step('print rbh value', ['echo', intermediate.edit_rbh_value])

  final_result = intermediate.then('launch')


def GenTests(api: TEST_DEPS):
  def led_props(input_properties):
    return api.properties(**{'$recipe_engine/led': input_properties})

  yield (api.test('get-builder') +
         api.properties(led_real_build_pb.InputProperties(get_cmd=['get-builder', 'chromium/try:linux-rel'])) +
         led_props(LedInputProperties(shadowed_bucket='bucket')) +
         api.post_process(post_process.StepCommandContains, 'led get-builder',
                          ['led', 'get-builder', 'chromium/try:linux-rel']) +
         api.post_process(post_process.StepCommandContains, 'led launch',
                          ['led', 'launch']) +
         api.post_process(post_process.DropExpectation))

  yield (api.test('get-build') +
         api.properties(led_real_build_pb.InputProperties(get_cmd=['get-build', '87654321'])) +
         led_props(LedInputProperties(shadowed_bucket='bucket')) +
         api.post_process(post_process.StepCommandContains, 'led get-build',
                          ['led', 'get-build', '87654321']) +
         api.post_process(post_process.StepCommandContains, 'led launch',
                          ['led', 'launch']) +
         api.post_process(post_process.DropExpectation))
