# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class LegacyAnnotationTestApi(recipe_test_api.RecipeTestApi):
  """For legacy `allow_subannotations` feature, the step status was deciced by
  the command's return code (i.e. is zero or not). However, since the
  `legacy_annotation` module runs the command as a sub-build/sub-luciexe.
  The step status is now the same as the status of the result build. This
  test api provides properties which represent different step status and
  help populate the sub-build placeholder.
  """

  @property
  def success_step(self):
    """Returns a StepTestData that indicating a succeeding step"""
    return self.m.step.sub_build(build_pb2.Build(status=common_pb2.SUCCESS))

  @property
  def failure_step(self):
    """Returns a StepTestData that fails the step and raises `step.StepFailure`.
    """
    ret = self.m.step.sub_build(build_pb2.Build(status=common_pb2.FAILURE))
    ret.retcode = 1
    return ret

  @property
  def infra_failure_step(self):
    """Returns a StepTestData that fails the step and raise `step.InfraFailure`.
    """
    ret = self.m.step.sub_build(
      build_pb2.Build(status=common_pb2.INFRA_FAILURE))
    ret.retcode = 1
    return ret

  @recipe_test_api.mod_test_data
  @staticmethod
  def simulate_kitchen():
    """Simulate Kitchen behavior in test instead of bbagent/luciexe behavior.
    """
    return True
