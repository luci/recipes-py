# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Iterator
from recipe_engine import recipe_test_api

from PB.recipes.recipe_engine.engine_tests import proto_properties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    properties,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  properties: properties.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API

PROPERTIES = proto_properties.TestProperties
ENV_PROPERTIES = proto_properties.EnvProperties


def RunSteps(
    api: DEPS,
    properties: proto_properties.TestProperties,
    env_props: proto_properties.EnvProperties,
) -> None:
  api.assertions.assertEqual(properties.an_int, 100)
  api.assertions.assertEqual(properties.some_string, 'hey there')

  api.assertions.assertEqual(env_props.STR_ENV, "sup")
  api.assertions.assertEqual(env_props.INT_ENV, 9000)


def GenTests(api: TEST_DEPS) -> Iterator[recipe_test_api.TestData]:
  yield (
    api.test('full')
    + api.properties(
        proto_properties.TestProperties(
            an_int=100,
            some_string='hey there',
        ),
        ignored_prop='yo')
    + api.properties.environ(
        proto_properties.EnvProperties(
            STR_ENV="sup",
            INT_ENV=9000,
        ))
    + api.post_process(lambda _check, _steps: {}))
