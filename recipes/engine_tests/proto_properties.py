# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipes.recipe_engine.engine_tests import proto_properties

DEPS = [
    'assertions',
    'properties',
]

PROPERTIES = proto_properties.TestProperties
ENV_PROPERTIES = proto_properties.EnvProperties


def RunSteps(api, properties, env_props):
  api.assertions.assertEqual(properties.an_int, 100)
  api.assertions.assertEqual(properties.some_string, 'hey there')

  api.assertions.assertEqual(env_props.STR_ENV, "sup")
  api.assertions.assertEqual(env_props.INT_ENV, 9000)


def GenTests(api):
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
