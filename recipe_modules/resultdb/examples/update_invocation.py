# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.config import List
from recipe_engine.post_process import DropExpectation
from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import instruction as instruction_pb

DEPS = [
    'resultdb',
    'properties',
]

PROPERTIES = {
    'gitiles_commit': Property(kind=dict),
    'gerrit_changes': Property(kind=List(dict)),
    'invocation': Property(kind=str),
}


def RunSteps(api, invocation, gitiles_commit, gerrit_changes):
  gitiles_commit = common_pb.GitilesCommit(**gitiles_commit)
  gerrit_changes = [
      common_pb.GerritChange(**change) for change in gerrit_changes
  ]
  api.resultdb.update_invocation(
      parent_inv=invocation,
      source_spec=invocation_pb.SourceSpec(
          sources=invocation_pb.Sources(
              gitiles_commit=gitiles_commit,
              changelists=gerrit_changes,
          )),
      is_source_spec_final=True,
      baseline_id='try:linux-rel',
      instructions=instruction_pb.Instructions(
          instructions=[
              instruction_pb.Instruction(
                  id="step_instruction",
                  type=instruction_pb.InstructionType.STEP_INSTRUCTION,
                  targeted_instructions=[
                      instruction_pb.TargetedInstruction(
                          targets=[
                              instruction_pb.InstructionTarget.LOCAL,
                          ],
                          content="this is step content",
                          dependencies=[
                              instruction_pb.InstructionDependency(
                                  invocation_id="another_inv_id",
                                  instruction_id="another_instruction",
                              )
                          ],
                      ),
                  ],
              ),
              instruction_pb.Instruction(
                  id="test_instruction",
                  type=instruction_pb.InstructionType.TEST_RESULT_INSTRUCTION,
                  targeted_instructions=[
                      instruction_pb.TargetedInstruction(
                          targets=[
                              instruction_pb.InstructionTarget.LOCAL,
                          ],
                          content="this is test content",
                          dependencies=[
                              instruction_pb.InstructionDependency(
                                  invocation_id="another_inv_id",
                                  instruction_id="another_instruction",
                              )
                          ],
                      ),
                  ],
                  instruction_filter=instruction_pb.InstructionFilter(
                      invocation_ids=instruction_pb
                      .InstructionFilterByInvocationID(
                          invocation_ids=["swarming-task-1"],
                          recursive=False,
                      ),),
              ),
          ],))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          gitiles_commit=dict(
              host='gitileshost',
              project='project/src',
              ref='ref7890',
              position=1234,
              commit_hash='hash'),
          gerrit_changes=[
              dict(
                  host='gerrithost',
                  project='project/src',
                  change=111,
                  patchset=2,
              )
          ],
          invocation='invocations/inv'),
      api.post_process(DropExpectation),
  )
