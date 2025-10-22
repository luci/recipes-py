# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from builtins import object
from past.builtins import basestring
import attr

from ..attr_util import attr_type, attr_dict_type

@attr.s(frozen=True, slots=True)
class TestCaseResult:
  # Raw Result of recipe.
  raw_result = attr.ib()  # type: result_pb2.RawResult
  # The log of each step that would have been run.
  ran_steps = attr.ib(factory=dict, validator=attr_dict_type(basestring, dict))
  # Annotations emitted for each step.
  annotations = attr.ib(factory=dict,
                        validator=attr_dict_type(basestring, dict))
  # Warnings issued during recipe execution.
  warnings = attr.ib(factory=dict, validator=attr_type(dict))
  # Uncaught exception triggered by recipe code or None.
  uncaught_exception = attr.ib(default=None)


def execute_test_case(recipe_deps, recipe_name, test_data) -> TestCaseResult:
  """Executes a single test case.

  Args:

    * recipe_deps (RecipeDeps)
    * recipe_name (basestring) - The recipe to run.
    * test_data (TestData) - The test data to use for the simulated run.

  Returns TestCaseResult
  """
  # pylint: disable=too-many-locals

  # Late imports to avoid importing 'PB'.
  from ..engine import RecipeEngine
  from ..engine_env import FakeEnviron
  from ..step_runner.sim import SimulationStepRunner
  from ..stream.invariants import StreamEngineInvariants
  from ..stream.simulator import SimulationStreamEngine
  from ...util import fix_json_object

  from recipe_engine import turboci
  for block in test_data.turboci_write_nodes:
    turboci.write_nodes(
        *block.nodes,
        turboci.reason(
            f'api.turboci_write_nodes() from {block.filename}:{block.lineno}'))

  step_runner = SimulationStepRunner(test_data)
  simulator = SimulationStreamEngine()
  stream_engine = StreamEngineInvariants.wrap(simulator)

  props = test_data.properties.copy()
  props = fix_json_object(props)
  props['recipe'] = str(recipe_name)

  environ = FakeEnviron()
  for key, value in test_data.environ.items():
    environ[key] = value

  raw_result, uncaught_exception = RecipeEngine.run_steps(
      recipe_deps, props, stream_engine, step_runner,
      environ, '', test_data.luci_context,
      num_logical_cores=8, memory_mb=16 * (1024**3), test_data=test_data,
      skip_setup_build=True)

  return TestCaseResult(
      raw_result=raw_result,
      ran_steps=step_runner.export_steps_ran(),
      annotations=simulator.annotations,
      uncaught_exception=uncaught_exception,
  )
