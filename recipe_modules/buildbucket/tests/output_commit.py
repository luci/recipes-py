# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This recipe tests the buildbucket.set_output_gitiles_commit function."""

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    platform,
    properties,
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  platform: platform.API
  properties: properties.API
  raw_io: raw_io.API
  step: step.API


def RunSteps(api: DEPS):
  api.buildbucket.set_output_gitiles_commit(
    common_pb2.GitilesCommit(
        host='chromium.googlesource.com',
        project='infra/infra',
        ref='refs/heads/main',
        id='a' * 40,
        position=42,
    ),
  )


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
