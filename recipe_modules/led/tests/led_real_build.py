# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import re

from recipe_engine import post_process
from recipe_engine.post_process import StepCommandContains
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
    'get_cmd': Property(default=None, kind=list),
}

def RunSteps(api, get_cmd):
  intermediate = api.led(*get_cmd)

  if api.led.launched_by_led:
    assert api.led.shadowed_bucket

  intermediate = intermediate.then(
      'edit-cr-cl', 'https://fake.url/c/project/123/+/456')

  intermediate = intermediate.then('edit', '-name', 'foobar')

  intermediate = intermediate.then('edit-recipe-bundle')

  api.step('print pre-launch', [
      'echo', api.proto.encode(intermediate.result, 'JSONPB')])

  api.step('print rbh value', ['echo', intermediate.edit_rbh_value])

  final_result = intermediate.then('launch')

def GenTests(api):
  def led_props(input_properties):
    return api.properties(**{'$recipe_engine/led': input_properties})

  yield (
      api.test('get-builder') +
      api.properties(get_cmd=['get-builder', 'chromium/try:linux-rel']) +
      led_props(InputProperties(shadowed_bucket='bucket')) +
      api.post_process(
          post_process.StepCommandContains, 'led get-builder',
          ['led', 'get-builder', '-real-build', 'chromium/try:linux-rel']) +
      api.post_process(
          post_process.StepCommandContains, 'led launch',
          ['led', 'launch', '-real-build']) +
      api.post_process(post_process.DropExpectation)
  )

  yield (
      api.test('get-builder w/ -real-build') +
      api.properties(
          get_cmd=['get-builder', '-real-build', 'chromium/try:linux-rel']) +
      api.post_process(
          post_process.StepCommandContains, 'led get-builder',
          ['led', 'get-builder', '-real-build', 'chromium/try:linux-rel']) +
      api.post_process(
          post_process.StepCommandContains, 'led launch',
          ['led', 'launch', '-real-build']) +
      api.post_process(post_process.DropExpectation)
  )

  yield (
      api.test('get-build') +
      api.properties(get_cmd=['get-build', '87654321']) +
      led_props(InputProperties(shadowed_bucket='bucket')) +
      api.post_process(
          post_process.StepCommandContains, 'led get-build',
          ['led', 'get-build', '-real-build', '87654321']) +
      api.post_process(
          post_process.StepCommandContains, 'led launch',
          ['led', 'launch', '-real-build']) +
      api.post_process(post_process.DropExpectation)
  )

  yield (
      api.test('get-build w/ -real-build') +
      api.properties(get_cmd=['get-build', '-real-build', '87654321']) +
      api.post_process(
          post_process.StepCommandContains, 'led get-build',
          ['led', 'get-build', '-real-build', '87654321']) +
      api.post_process(
          post_process.StepCommandContains, 'led launch',
          ['led', 'launch', '-real-build']) +
      api.post_process(post_process.DropExpectation)
  )
