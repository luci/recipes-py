# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import buildbucket


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API


BBID = 881234567890


def RunSteps(api: DEPS):
  bld = api.buildbucket.get(
      BBID,
      test_data=build_pb2.Build(id=BBID, builder_info={'description': 'foo'}))
  assert bld.builder_info.description == 'foo', repr(bld)


def GenTests(api: RecipeTestApi):
  yield api.test('basic') + api.post_process(post_process.DropExpectation)
