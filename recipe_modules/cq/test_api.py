# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Wrapper for CV Test API."""

from recipe_engine import recipe_test_api


class CQTestApi(recipe_test_api.RecipeTestApi):
  # Common Run modes.
  NEW_PATCHSET_RUN = 'NEW_PATCHSET_RUN'
  DRY_RUN = 'DRY_RUN'
  QUICK_DRY_RUN = 'QUICK_DRY_RUN'
  FULL_RUN = 'FULL_RUN'

  def __call__(self, *args, **kwargs):
    return self.m.properties(
        **{f'$recipe_engine/cq': self.m.cv.input_props(*args, **kwargs)})
