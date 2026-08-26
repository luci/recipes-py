# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.resultdb.proto.v1 import (instruction as
                                                       instruction_pb)

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    resultdb,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  resultdb: resultdb.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  resultdb: resultdb.TEST_API


def RunSteps(api: DEPS):
  instructions = api.resultdb.get_invocation_instructions(
      inv_name='invocations/build-8831400474790691137')
  api.assertions.assertEqual(1, len(instructions.instructions))
  api.assertions.assertEqual('instruction1', instructions.instructions[0].id)


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.resultdb.get_invocation_instructions(
          instruction_pb.Instructions(instructions=[
              instruction_pb.Instruction(
                  id='instruction1',
                  descriptive_name='test instructions',
                  type=instruction_pb.InstructionType.STEP_INSTRUCTION,
                  targeted_instructions=[]),
          ])),
      api.post_process(DropExpectation),
  )
