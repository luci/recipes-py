# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Legacy Annotation module provides support for running a command emitting
legacy @@@annotation@@@ in the new luciexe mode.

The output annotations is converted to a build proto and all steps in the build
will appear as the child steps of the launched cmd/step in the current running
build (using the Merge Step feature from luciexe protocol). This is the
replacement for allow_subannotation feature in the legacy annotate mode.
"""

from google.protobuf import json_format as jsonpb
from six import iteritems

from recipe_engine import recipe_api
from recipe_engine.types import ResourceCost as _ResourceCost
from recipe_engine.util import Placeholder

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class LegacyAnnotationApi(recipe_api.RecipeApiPlain):
  concurrency_client = recipe_api.RequireClient('concurrency')

  def __call__(self, name, cmd,
               timeout=None, step_test_data=None, cost=_ResourceCost()):
    """Runs cmd that is emitting legacy @@@annotation@@@.

    Currently, it will run the command as sub_build if running in luciexe
    mode or simulation mode. Otherwise, it will fall back to launch a step
    with allow_subannotation set to true.
    """
    if not self.concurrency_client.supports_concurrency:  # pragma: no cover
      # TODO(yiwzhang): Remove after bbagent is fully rolled out.
      return self.m.step(name, cmd,
                        allow_subannotations=True,
                        timeout=timeout,
                        step_test_data=step_test_data,
                        cost=cost)

    run_annotations_luciexe = self.m.cipd.ensure_tool(
      'infra/tools/run_annotations/${platform}', 'latest')
    cmd = [run_annotations_luciexe, '--'] + cmd
    if step_test_data:
      _step_test_data = step_test_data
      step_test_data = lambda: self.test_api.success_step + _step_test_data()
    else: # pragma: no cover
      step_test_data = lambda: self.test_api.success_step
    ret = self.m.step.sub_build(name, cmd, build_pb2.Build(),
                                timeout=timeout,
                                step_test_data=step_test_data,
                                cost=cost)
    ret.presentation.properties.update(
      jsonpb.MessageToDict(ret.step.sub_build.output.properties))
    return ret
