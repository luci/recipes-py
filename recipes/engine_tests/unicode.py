# -*- coding: utf-8 -*-
# Copyright 2016 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  result = api.step(
      'trigger some junk',
      cmd=['echo', 'hi'],
  )
  result.presentation.logs['thing'] = [
      u'hiiiii 😀…' , # This is valid, and should be displayed.
      b'\xe4\xb8\xad', # Raw utf-8 bytes will be decoded.
  ]


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
