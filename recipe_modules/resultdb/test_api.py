# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations
from collections.abc import Mapping, Sequence
from google.protobuf import message as message_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import instruction as instruction_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb

import json

from google.protobuf import json_format

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2

from . import common


class ResultDBTestApi(recipe_test_api.RecipeTestApi):

  # Expose serialize and deserialize functions.

  serialize = staticmethod(common.serialize)
  deserialize = staticmethod(common.deserialize)
  Invocation = common.Invocation

  def query(
      self,
      inv_bundle: Mapping[str, common.Invocation],
      step_name: str | None = None,
  ) -> recipe_test_api.StepTestData:
    """Emulates query() return value.

    Args:
      inv_bundle: a dict {inv_id: test_api.Invocation}.
      step_name: the name of the step to simulate.
    """
    step_name = step_name or 'rdb query'
    return self.step_data(
        step_name,
        self.m.raw_io.stream_output_text(common.serialize(inv_bundle)),
    )

  def get_included_invocations(
      self,
      invs: Sequence[str],
      step_name: str = 'get_included_invocations',
  ) -> recipe_test_api.StepTestData:
    """Emulates get_included_invocations() step output.

    Args:
        invs (list): List of strs of the included invocation names to simulate.
        step_name (str): the name of the step to simulate.
    """
    inv = invocation_pb2.Invocation(included_invocations=invs)

    return self._proto_step_result(inv, step_name)

  def get_invocation_instructions(
      self,
      instructions: instruction_pb.Instructions,
      step_name: str = 'get_invocation_instructions',
  ) -> recipe_test_api.StepTestData:
    """Emulates get_invocation_instructions() step output.

    Args:
        invs (instruction_pb2.Instructions): Instructions of the invocation to
          simulate.
        step_name (str): the name of the step to simulate.
    """
    inv = invocation_pb2.Invocation(instructions=instructions)

    return self._proto_step_result(inv, step_name)

  def query_test_result_statistics(
      self,
      res: resultdb.QueryTestResultStatisticsResponse,
      step_name: str = 'query_test_result_statistics',
  ) -> recipe_test_api.StepTestData:
    """Emulates query_test_result_statistics() return value.

    Args:
        res (proto.v1.resultdb.QueryTestResultStatisticsResponse object): the
          response to simulate.
        step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def upload_invocation_artifacts(
      self,
      res: recorder.BatchCreateArtifactsResponse,
      step_name: str = 'upload_invocation_artifacts',
  ) -> recipe_test_api.StepTestData:
    """Emulates upload_invocation_artifacts() return value.

    Args:
        res (proto.v1.resultdb.BatchCreateArtifactsResponse object): the
          response to simulate.
        step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_test_results(
      self,
      res: resultdb.QueryTestResultsResponse,
      step_name: str = 'query_test_results',
  ) -> recipe_test_api.StepTestData:
    """Emulates query_test_results() return value.

    Args:
      res (proto.v1.resultdb.QueryTestResultsResponse object): the response.
      step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_test_variants(
      self,
      res: resultdb.QueryTestVariantsResponse,
      step_name: str = 'query_test_variants',
  ) -> recipe_test_api.StepTestData:
    """Emulates query_test_variants() return value.

    Args:
      res (proto.v1.resultdb.QueryTestVariantsResponse object): the response.
      step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_new_test_variants(
      self,
      res: resultdb.QueryNewTestVariantsResponse,
      step_name: str = 'query_new_test_variants',
  ) -> recipe_test_api.StepTestData:
    """Emulates query_new_test_results() return value

    Args:
      res (proto.v1.resultdb.QueryNewtestVariantsResponse object): the response.
      step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def _proto_step_result(
      self, message: message_pb.Message, step_name: str
  ) -> recipe_test_api.StepTestData:
    """Utility method that converts a proto into JSON-formatted step data."""
    res = json_format.MessageToDict(message)
    return self.step_data(
        step_name,
        self.m.json.output_stream(res),
    )
