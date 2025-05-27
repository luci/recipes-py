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

from __future__ import annotations

from google.protobuf import json_format as jsonpb

from recipe_engine import recipe_api
from recipe_engine.engine_types import ResourceCost as _ResourceCost
from recipe_engine.util import Placeholder

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class LegacyAnnotationApi(recipe_api.RecipeApi):
  concurrency_client = recipe_api.RequireClient('concurrency')
  step_client = recipe_api.RequireClient('step')

  def __call__(self, name, cmd,
               timeout=None, step_test_data=None, cost=_ResourceCost(),
               legacy_global_namespace=False):
    """Runs cmd that is emitting legacy @@@annotation@@@.

    Currently, it will run the command as sub_build if running in luciexe
    mode or simulation mode. Otherwise, it will fall back to launch a step
    with allow_subannotation set to true.

    If `legacy_global_namespace` is True, this enables an even more-legacy
    global namespace merging mode. Do not enable this. See crbug.com/1310155.
    """
    # concurrency is enabled when running recipe in bbagent/luciexe mode.
    run_kitchen_mode = not self.concurrency_client.supports_concurrency
    if self._test_data.enabled:
      run_kitchen_mode = self._test_data.get('simulate_kitchen', False)

    if run_kitchen_mode:
      # TODO(yiwzhang): Remove after bbagent is fully rolled out.
      self.m.step._validate_cmd_list(cmd)
      with self.m.context(env_prefixes={'PATH': self.m.step._prefix_path}):
        env_prefixes = self.m.context.env_prefixes
      return self.m.step._run_or_raise_step(self.step_client.StepConfig(
          name=name,
          cmd=cmd,
          cost=self.m.step._normalize_cost(cost),
          cwd=self.m.step._normalize_cwd(self.m.context.cwd),
          env=self.m.context.env,
          env_prefixes=self.m.step._to_env_affix(env_prefixes),
          env_suffixes=self.m.step._to_env_affix(self.m.context.env_suffixes),
          allow_subannotations=True,
          timeout=timeout,
          luci_context=self.m.context.luci_context,
          infra_step=self.m.context.infra_step,
          step_test_data=step_test_data,
      ))

    run_annotations_luciexe = self.m.cipd.ensure_tool(
      'infra/tools/run_annotations/${platform}', 'latest')
    cmd = [run_annotations_luciexe, '--'] + cmd
    if step_test_data:
      _step_test_data = step_test_data
      step_test_data = lambda: self.test_api.success_step + _step_test_data()
    else: # pragma: no cover
      step_test_data = lambda: self.test_api.success_step
    ret = self.m.step.sub_build(
        name,
        cmd,
        build_pb2.Build(),
        timeout=timeout,
        step_test_data=step_test_data,
        cost=cost,
        legacy_global_namespace=legacy_global_namespace,
    )
    if not legacy_global_namespace:
      ret.presentation.properties.update(
        jsonpb.MessageToDict(ret.step.sub_build.output.properties))
    return ret
