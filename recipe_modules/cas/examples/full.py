# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    cas,
    file,
    path,
    properties,
    runtime,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  cas: cas.API
  file: file.API
  path: path.API
  properties: properties.API
  runtime: runtime.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  runtime: runtime.TEST_API


def RunSteps(api: DEPS):
  api.cas.instance

  # Prepare files.
  temp = api.path.mkdtemp('cas-example')
  api.step('touch a', ['touch', temp / 'a'])
  api.step('touch b', ['touch', temp / 'b'])
  api.file.ensure_directory('mkdirs', temp / 'sub' / 'dir')
  api.step('touch d', ['touch', temp / 'sub' / 'dir' / 'd'])

  digest = api.cas.archive('archive', temp,
                           *[temp / p for p in ('a', 'b', 'sub')])
  # You can also archive the entire directory.
  with api.cas.with_instance('projects/other-cas-server/instances/instance'):
    api.cas.archive('archive directory', temp, log_level='debug', timeout=60)

  out = api.path.mkdtemp('cas-output')
  api.cas.download('download', digest, out)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
  yield api.test('experimental') + api.runtime(is_experimental=True)
