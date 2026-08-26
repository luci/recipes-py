# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""An example of a recipe wrapping legacy analyzers."""

from __future__ import annotations

from google.protobuf import json_format

from recipe_engine import post_process

from PB.tricium.data import Data

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    file,
    path,
    tricium,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  file: file.API
  path: path.API
  tricium: tricium.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  file: file.TEST_API


def RunSteps(api: DEPS):
  checkout_base = api.path.cleanup_dir / 'checkout'
  api.file.write_text('one', checkout_base / 'one.txt', 'one')
  api.file.write_text('two', checkout_base / 'foo' / 'two.txt', 'two')
  api.file.write_text('png', checkout_base / 'image.png', 'png')

  analyzers = [
      api.tricium.analyzers.SPACEY,
      api.tricium.analyzers.PYLINT,
      api.tricium.analyzers.CPPLINT,
      api.tricium.analyzers.COMMITCHECK,
  ]
  # Analyzers can also be added via their names:
  analyzers.append(api.tricium.analyzers.by_name()['Eslint'])

  api.tricium.run_legacy(
      analyzers, checkout_base, ['one.py', 'foo/two.py', 'image.png'], commit_message='msg')


def GenTests(api: TEST_DEPS):

  def results_json(num_comments):
    results = Data.Results()
    results.comments.extend([
        Data.Comment(category='X', message=str(i), path='x')
        for i in range(num_comments)
    ])
    return json_format.MessageToJson(results)

  yield (api.test('success') + api.buildbucket.try_build(project='chrome') +
         api.step_data('Spacey.read results',
                       api.file.read_text(results_json(num_comments=1))) +
         api.post_check(post_process.StatusSuccess) +
         api.post_process(post_process.DropExpectation))

  yield (api.test('with_failure') +
         api.buildbucket.try_build(project='chrome') +
         api.step_data('Spacey.run analyzer', retcode=1) +
         api.post_process(post_process.DropExpectation))

  yield (api.test('many_comments') +
         api.buildbucket.try_build(project='chrome') +
         api.step_data('Pylint.read results',
                       api.file.read_text(results_json(num_comments=51))) +
         api.post_process(post_process.DropExpectation))
