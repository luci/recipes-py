#!/usr/bin/env vpython3
# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_stability."""
from __future__ import annotations

from google.protobuf import json_format

from PB.recipe_modules.recipe_engine.luci_analysis.tests import query_stability_test as query_stability_test_pb
from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    json,
    luci_analysis,
    properties,
    raw_io,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  json: json.API
  luci_analysis: luci_analysis.API
  properties: properties.API
  raw_io: raw_io.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  json: json.TEST_API
  luci_analysis: luci_analysis.TEST_API
  properties: properties.TEST_API
  raw_io: raw_io.TEST_API

INLINE_PROPERTIES_PROTO = """
message Changelist {
  string change = 1;
  string host = 2;
  string patchset = 3;
  string project = 4;
}

message GitilesCommit {
  string host = 1;
  string project = 2;
  string ref = 3;
  string commit_hash = 4 [json_name = "commitHash"];
  string position = 5;
}

message Sources {
  repeated Changelist changelists = 1;
  GitilesCommit gitiles_commit = 2 [json_name = "gitilesCommit"];
}

message Variant {
  map<string, string> def = 1;
}

message TestVariant {
  string test_id = 1 [json_name = "testId"];
  Variant variant = 2;
  Sources sources = 3;
}

message InputProperties {
  repeated TestVariant input_list = 1;
}
"""

PROPERTIES = query_stability_test_pb.InputProperties


def RunSteps(api: DEPS, props: query_stability_test_pb.InputProperties):
  input_list = [
      json_format.MessageToDict(i, preserving_proto_field_name=False)
      for i in props.input_list
  ]
  analysis, criteria = api.luci_analysis.query_stability(input_list, "chromeos")
  api.assertions.assertGreaterEqual(len(analysis), 1)
  api.assertions.assertIsNotNone(criteria)


def GenTests(api: TEST_DEPS):
  input_list_dicts = api.luci_analysis.query_stability_example_input()
  input_list = [
      json_format.ParseDict(
          d, query_stability_test_pb.TestVariant(), ignore_unknown_fields=True)
      for d in input_list_dicts
  ]
  output = api.luci_analysis.query_stability_example_output()

  yield api.test(
      'basic',
      api.properties(
          query_stability_test_pb.InputProperties(input_list=input_list)),
      api.step_data(
          'query LUCI Analysis for stability.rpc call',
          stdout=api.raw_io.output_text(api.json.dumps(output)),
      ),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS')

  yield api.test(
      'step_failure',
      api.properties(
          query_stability_test_pb.InputProperties(input_list=input_list)),
      api.step_data(
          'query LUCI Analysis for stability.rpc call',
          stdout=api.raw_io.output_text(api.json.dumps({})),
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE')
