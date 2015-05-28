# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

class ExampleApi(recipe_api.RecipeApi):
  """ExampleApi provides support for the example/* recipes."""

  def __call__(self, name):
    return self.m.step(name, ['true'])

  @recipe_api.non_step
  def explicit_non_composite_step(self):
    # normally this would count as a composite step, since it runs substeps.
    # However we want these steps to actually run in the parent context
    # (for some reason), so we mark the function as not a step.
    self("bogus")
    self("steps")
