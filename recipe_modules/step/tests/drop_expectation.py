# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

# This is not really a test of the step module, but it's the most convenient
# way to test DropExpectations.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import step


@dataclass
class DEPS(RecipeScriptApi):
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  with api.step.nest('abc'):
    api.step.empty('def')
  with api.step.nest('abcdef'):
    api.step.empty('ghi')
  api.step.empty('abc.de.f')


def GenTests(api: TEST_DEPS):
  yield api.test(
      'one-arg',
      api.post_process(post_process.MustRun, 'abc'),
      api.post_process(post_process.MustRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc.de'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc.de.f'),
      api.post_process(post_process.DoesNotRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multiple-args',
      api.post_process(post_process.MustRun, 'abc'),
      api.post_process(post_process.MustRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc', 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc.def'),
      api.post_process(post_process.DoesNotRun, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-args',
      api.post_process(post_process.MustRun, 'abc'),
      api.post_process(post_process.MustRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation),
      api.post_process(post_process.DoesNotRun, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc.def'),
      api.post_process(post_process.DoesNotRun, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef.ghi'),
      api.post_process(post_process.DoesNotRun, 'abc.de.f'),
  )
