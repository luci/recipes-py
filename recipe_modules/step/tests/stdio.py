# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  raw_io: raw_io.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  raw_io: raw_io.TEST_API


def RunSteps(api: DEPS):
  # Read command's stdout and stderr.
  step_result = api.step('echo', ['echo', 'Hello World'],
      stdout=api.raw_io.output_text(),
      stderr=api.raw_io.output_text())

  if step_result.stdout == "stdout":
    api.step.empty('mocked stdout')
  if step_result.stderr == "stderr":
    api.step.empty('mocked stderr')

  # Pass stuff to command's stdin, read it from stdout.
  step_result = api.step('cat', ['cat'],
      stdin=api.raw_io.input_text(data='hello'),
      stdout=api.raw_io.output('out'))

  # Example of auto-mocking stdout. '\n' appended to mock 'echo' behavior.
  step_result = api.step(
      'automock',
      ['echo', 'huh'],
      stdout=api.raw_io.output_text('out'),
      step_test_data=(
          lambda: api.raw_io.test_api.stream_output_text('huh\n')))
  if step_result.stdout == 'huh\n':
    api.step.empty('inline mock')
  else:
    api.step.empty('test mock', step_text=step_result.stdout)


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.post_check(lambda check, steps: check('mocked stdout') not in steps),
      api.post_check(lambda check, steps: check('mocked stderr') not in steps),
      api.post_check(lambda check, steps: check('inline mock') in steps),
      api.post_check(lambda check, steps: check('test mock') not in steps),
  )

  yield api.test(
      'mocking',
      api.step_data(
          'echo',
          stdout=api.raw_io.output_text('stdout'),
          stderr=api.raw_io.output_text('stderr'),
      ),
      api.override_step_data(
          'automock',
          stdout=api.raw_io.output_text('OVERRIDE'),
      ),
      api.post_check(lambda check, steps: check('mocked stdout') in steps),
      api.post_check(lambda check, steps: check('mocked stderr') in steps),
      api.post_check(lambda check, steps: check('inline mock') not in steps),
      api.post_check(lambda check, steps: check('test mock') in steps),
  )
