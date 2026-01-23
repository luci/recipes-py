# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import json_format

from PB.recipe_modules.recipe_engine.resultdb.examples import update_invocation as update_invocation_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import instruction as instruction_pb
from recipe_engine.post_process import DropExpectation

DEPS = [
    'resultdb',
    'properties',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  message GitilesCommit {
    string host = 1;
    string project = 2;
    string ref = 3;
    uint32 position = 4;
    string commit_hash = 5 [json_name = "commit_hash"];
  }
  message GerritChange {
    string host = 1;
    string project = 2;
    int64 change = 3;
    int64 patchset = 4;
  }
  GitilesCommit gitiles_commit = 1 [json_name = "gitiles_commits"];
  repeated GerritChange gerrit_changes = 2 [json_name = "gerrit_changes"];
  string invocation = 3;
}
"""

PROPERTIES = update_invocation_pb.InputProperties


def RunSteps(api, props: update_invocation_pb.InputProperties):
  gitiles_commit = common_pb.GitilesCommit()
  json_format.ParseDict(
      json_format.MessageToDict(props.gitiles_commit),
      gitiles_commit,
      ignore_unknown_fields=True)

  gerrit_changes = []
  for change in props.gerrit_changes:
    gc = common_pb.GerritChange()
    json_format.ParseDict(
        json_format.MessageToDict(change), gc, ignore_unknown_fields=True)
    gerrit_changes.append(gc)

  api.resultdb.update_invocation(
      parent_inv=props.invocation,
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
          update_invocation_pb.InputProperties(
              gitiles_commit=update_invocation_pb.InputProperties.GitilesCommit(
                  host='gitileshost',
                  project='project/src',
                  ref='ref7890',
                  position=1234,
                  commit_hash='hash'),
              gerrit_changes=[
                  update_invocation_pb.InputProperties.GerritChange(
                      host='gerrithost',
                      project='project/src',
                      change=111,
                      patchset=2,
                  )
              ],
              invocation='invocations/inv')),
      api.post_process(DropExpectation),
  )
