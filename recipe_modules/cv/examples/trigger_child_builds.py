# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations
from collections.abc import Callable, Mapping
from typing import Any
from recipe_engine import post_process_inputs

from collections.abc import Iterator
from recipe_engine import recipe_test_api

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    buildbucket,
    cv,
    json,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  buildbucket: buildbucket.API
  cv: cv.API
  json: json.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  cv: cv.TEST_API
  json: json.TEST_API


def RunSteps(api: DEPS) -> None:
  properties = {'foo': 'bar'}
  properties.update(api.cv.props_for_child_build)
  req = api.buildbucket.schedule_request(
      builder='child',
      gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),
      properties=properties)
  child_builds = api.buildbucket.schedule([req])
  api.cv.record_triggered_builds(*child_builds)


def GenTests(api: TEST_DEPS) -> Iterator[recipe_test_api.TestData]:

  def check_has_bb_tag(
      check: Callable[..., bool],
      steps: Mapping[str, post_process_inputs.Step],
      key: str,
      value: str,
  ) -> None:
    req = api.json.loads(steps['buildbucket.schedule'].logs['request'])
    tags = req['requests'][0]['scheduleBuild'].get('tags', [])
    check({'key': key, 'value': value} in tags)

  def extract_cq_props(
      steps: Mapping[str, post_process_inputs.Step],
  ) -> dict[str, Any]:
    req = api.json.loads(steps['buildbucket.schedule'].logs['request'])
    return req['requests'][0]['scheduleBuild'].get('properties', {}).get(
        '$recipe_engine/cq', {})

  def check_set_to(
      check: Callable[..., bool],
      steps: Mapping[str, post_process_inputs.Step],
      key: str,
      value: Any,
  ) -> None:
    props = extract_cq_props(steps)
    check(props[key] == value)

  def check_unset(
      check: Callable[..., bool],
      steps: Mapping[str, post_process_inputs.Step],
      key: str,
  ) -> None:
    props = extract_cq_props(steps)
    check(key not in props)

  yield (api.test('typical') + api.buildbucket.try_build() +
         api.cv(run_mode=api.cv.FULL_RUN) +
         api.post_check(check_set_to, 'active', True) +
         api.post_check(check_set_to, 'run_mode', 'FULL_RUN') +
         api.post_check(check_unset, 'top_level') +
         api.post_process(post_process.DropExpectation))
  yield (api.test('grand-child')
         # Unfortunate coupling: experimental means special tag, too.
         + api.buildbucket.try_build(
             tags=api.buildbucket.tags(cq_experimental='true')) +
         api.cv(run_mode=api.cv.DRY_RUN, top_level=False, experimental=True) +
         api.post_check(check_set_to, 'active', True) +
         api.post_check(check_set_to, 'run_mode', 'DRY_RUN') +
         api.post_check(check_set_to, 'experimental', True) +
         api.post_check(check_has_bb_tag, 'cq_experimental', 'true') +
         api.post_check(check_unset, 'top_level') +
         api.post_process(post_process.DropExpectation))
  yield (api.test('not-a-cq-run') + api.post_check(check_unset, 'active') +
         api.post_process(post_process.DropExpectation))
