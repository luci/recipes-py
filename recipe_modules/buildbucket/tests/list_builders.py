# Copyright 2022 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import buildbucket


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API


def RunSteps(api: DEPS):
  api.buildbucket.list_builders(
      'project', 'bucket', step_name='a step')


def GenTests(api: TEST_DEPS):
  yield (
      api.test('basic') +
      api.buildbucket.simulated_list_builders(
          ['builder-1', 'builder-2'],
          step_name='a step')
  )
