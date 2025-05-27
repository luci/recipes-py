# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

class StepTestApi(recipe_test_api.RecipeTestApi):

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def sub_build(build):
    """Returns the output placeholder for a launched sub build/luciexe.

    If input build is None, it simulates the behavior that the launched luciexe
    does not write its final build proto to the output file.
    """
    if not isinstance(build, (type(None), build_pb2.Build)): # pragma: no cover
      raise ValueError('expected type Build or None; got %r' % build)
    retVal = None
    if build:
      retVal = build_pb2.Build()
      retVal.CopyFrom(build)
    return retVal, None, None

  @recipe_test_api.mod_test_data
  @staticmethod
  def initial_build_create_time(seconds):  # pragma: no cover
    """Sets the create time of the initial build for luciexe."""
    # TODO: See tests/sub_build.clear_fields_of_input_build which would cover
    # this, but is disabled in python3.
    return seconds

  @recipe_test_api.mod_test_data
  @staticmethod
  def initial_build_start_time(seconds):  # pragma: no cover
    """Sets the create time of the initial build for luciexe."""
    # TODO: See tests/sub_build.clear_fields_of_input_build which would cover
    # this, but is disabled in python3.
    return seconds
