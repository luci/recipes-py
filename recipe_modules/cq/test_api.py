# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2

from recipe_engine import recipe_test_api


class CQTestApi(recipe_test_api.RecipeTestApi):
  # Common Run modes.
  NEW_PATCHSET_RUN = 'NEW_PATCHSET_RUN'
  DRY_RUN = 'DRY_RUN'
  QUICK_DRY_RUN = 'QUICK_DRY_RUN'
  FULL_RUN = 'FULL_RUN'

  def __call__(
      self,
      run_mode = None,
      top_level=True,
      experimental=False,
      owner_is_googler=False):
    """Simulate a build triggered by CQ."""
    assert isinstance(run_mode, str), '%r (%s)' % (run_mode, type(run_mode))
    input_props = cq_pb2.Input(active=True, run_mode=run_mode)

    assert isinstance(top_level, bool), '%r (%s)' % (top_level, type(top_level))
    input_props.top_level = top_level

    assert isinstance(experimental, bool), '%r (%s)' % (
        experimental, type(experimental))
    input_props.experimental = experimental

    assert isinstance(owner_is_googler, bool), '%r (%s)' % (
        owner_is_googler, type(owner_is_googler))
    input_props.owner_is_googler = owner_is_googler

    return self.m.properties(**{'$recipe_engine/cq': input_props})
