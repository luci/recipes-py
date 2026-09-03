# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2
from recipe_engine import post_process, recipe_test_api


class CVTestApi(recipe_test_api.RecipeTestApi):
  # Common Run modes.
  NEW_PATCHSET_RUN = 'NEW_PATCHSET_RUN'
  DRY_RUN = 'DRY_RUN'
  QUICK_DRY_RUN = 'QUICK_DRY_RUN'
  FULL_RUN = 'FULL_RUN'

  def input_props(self,
                  run_mode=None,
                  top_level=True,
                  experimental=False,
                  owner_is_googler=False):
    """Simulate a build triggered by CV."""
    assert isinstance(run_mode, str), '%r (%s)' % (run_mode, type(run_mode))
    input_props = cq_pb2.Input(active=True, run_mode=run_mode)

    assert isinstance(top_level, bool), '%r (%s)' % (top_level, type(top_level))
    input_props.top_level = top_level

    assert isinstance(experimental,
                      bool), '%r (%s)' % (experimental, type(experimental))
    input_props.experimental = experimental

    assert isinstance(
        owner_is_googler,
        bool), '%r (%s)' % (owner_is_googler, type(owner_is_googler))
    input_props.owner_is_googler = owner_is_googler

    return input_props

  def __call__(self, *args, **kwargs):
    return self.m.properties(
        **{f'$recipe_engine/cv': self.input_props(*args, **kwargs)})

  def check_triggered_build_ids(
      self,
      *args: Any,
      step_name: str | None = None,
      **kwargs: Any,
  ) -> recipe_test_api.TestData | None:
    """Checks that record_triggered_build_ids recorded expected build IDs.

    Args:
      *args: Expected Buildbucket build IDs (ints, strings, or Build objects),
        or (check, step_odict, *expected_build_ids) when used as a post-process
        hook.
      step_name: Optional step name. If specified, only the output properties of
        that step are checked; otherwise the build-level output properties are
        checked.
      **kwargs: Additional keyword arguments.

    Returns:
      TestData if called directly, or None if called within post_process.
    """
    if (len(args) >= 2 and callable(args[0]) and
        isinstance(args[1], Mapping)):
      check = args[0]
      step_odict = args[1]
      expected_ids = args[2:]
      if (len(expected_ids) == 1 and
          isinstance(expected_ids[0], (list, tuple, Sequence)) and
          not isinstance(expected_ids[0], (str, bytes))):
        expected_ids = expected_ids[0]
      expected = [str(getattr(bid, 'id', bid)) for bid in expected_ids]

      if step_name is not None:
        check(step_name in step_odict)
        props = step_odict[step_name].output_properties
      else:
        props = post_process.GetBuildProperties(step_odict)

      actual = [str(x) for x in props.get('triggered_build_ids', [])]
      check(actual == expected)

      cv_output = props.get('$recipe_engine/cv/output') or {}
      cv_bids = [
          str(x)
          for x in cv_output.get(
              'triggeredBuildIds', cv_output.get('triggered_build_ids', []))
      ]
      check(cv_bids == expected)

      cq_output = props.get('$recipe_engine/cq/output') or {}
      cq_bids = [
          str(x)
          for x in cq_output.get(
              'triggeredBuildIds', cq_output.get('triggered_build_ids', []))
      ]
      check(cq_bids == expected)

      return None

    return self.post_process(
        self.check_triggered_build_ids,
        *args,
        step_name=step_name,
        **kwargs,
    )
