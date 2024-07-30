# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.resultdb.proto.v1 import (instruction as
                                                       instruction_pb)

DEPS = [
    'recipe_engine/assertions',
    'resultdb',
]


def RunSteps(api):
  instructions = api.resultdb.get_invocation_instructions(
      inv_name='invocations/build-8831400474790691137')
  api.assertions.assertEqual(1, len(instructions.instructions))
  api.assertions.assertEqual('instruction1', instructions.instructions[0].id)


def GenTests(api):
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
