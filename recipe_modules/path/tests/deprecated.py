# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process, recipe_api

DEPS = [
    'path',
    'step',
]


@recipe_api.ignore_warnings('recipe_engine/CHECKOUT_DIR_DEPRECATED')
def RunSteps(api):
  api.path.checkout_dir = api.path.start_dir
  assert api.path.checkout_dir == api.path.start_dir

  api.step.empty('cache', step_text=str(api.path.cache_dir))
  api.step.empty('cleanup', step_text=str(api.path.cleanup_dir))
  api.step.empty('home', step_text=str(api.path.home_dir))
  api.step.empty('start_dir', step_text=str(api.path.start_dir))
  api.step.empty('tmp_base', step_text=str(api.path.tmp_base_dir))

  api.step.empty('checkout', step_text=str(api.path.checkout_dir))


def GenTests(api):

  @recipe_api.ignore_warnings('recipe_engine/PATH_GETITEM_DEPRECATED')
  def equals(name):
    return api.post_process(post_process.StepTextEquals, name, api.path[name])

  yield api.test(
      'equal',
      equals('cache'),
      equals('cleanup'),
      equals('home'),
      equals('start_dir'),
      equals('tmp_base'),
      equals('checkout'),
      api.post_process(post_process.DropExpectation),
  )
