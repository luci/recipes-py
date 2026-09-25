# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from typing import Any, Literal

import json

from recipe_engine import recipe_test_api

from .api import dumps, loads


class JsonTestApi(recipe_test_api.RecipeTestApi):

  @staticmethod
  def dumps(*args: Any, **kwargs: Any) -> str:
    """Works like `json.dumps`."""
    return dumps(*args, **kwargs)

  @staticmethod
  def loads(data: str | bytes, **kwargs: Any) -> Any:
    """Works like `json.loads`, but strips out unicode objects (replacing them
    with utf8-encoded str objects)."""
    return loads(data, **kwargs)

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(
      data: Any, retcode: int | None = None, name: str | None = None
  ) -> tuple[str, int | None, str | None]:
    """Supplies placeholder data for a json.output. `data` should be a jsonish
    python object (e.g. dict, list, str, bool, int, etc). It will be dumped out
    with json.dumps and the step will be observed to return that dumped value.
    """
    return json.dumps(data, indent=2, sort_keys=True), retcode, name

  @recipe_test_api.placeholder_step_data('output')
  @staticmethod
  def invalid(
      raw_data_str: str, retcode: int | None = None, name: str | None = None
  ) -> tuple[str, int | None, str | None]:
    """Can be used to supply data for a json.output, except that it takes a raw
    string rather than a json object."""
    return raw_data_str, retcode, name

  def output_stream(
      self,
      data: Any,
      stream: Literal['stdout', 'stderr'] = 'stdout',
      retcode: int | None = None,
      name: str | None = None,
  ) -> recipe_test_api.StepTestData:
    assert stream in ('stdout', 'stderr')
    ret = recipe_test_api.StepTestData()
    step_data = self.output(data, retcode=retcode, name=name)
    setattr(ret, stream, step_data.unwrap_placeholder())
    return ret

  @recipe_test_api.placeholder_step_data('output')
  @staticmethod
  def backing_file_missing(
      retcode: int | None = None, name: str | None = None
  ) -> tuple[None, int | None, str | None]:
    """Simulates a missing backing file.

    Only valid if the corresponding placeholder has `leak_to` specified.
    """
    # Passing None as the data of a placeholder causes the placeholder to
    # behave during testing as if its backing file was missing.
    return None, retcode, name
