# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

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

  def query(self, inv_bundle, step_name=None):
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

  def get_included_invocations(self, invs,
                               step_name='get_included_invocations'):
    """Emulates get_included_invocations() step output.

    Args:
        invs (list): List of strs of the included invocation names to simulate.
        step_name (str): the name of the step to simulate.
    """
    inv = invocation_pb2.Invocation(included_invocations=invs)

    return self._proto_step_result(inv, step_name)

  def get_invocation_instructions(self,
                                  instructions,
                                  step_name='get_invocation_instructions'):
    """Emulates get_invocation_instructions() step output.

    Args:
        invs (instruction_pb2.Instructions): Instructions of the invocation to
          simulate.
        step_name (str): the name of the step to simulate.
    """
    inv = invocation_pb2.Invocation(instructions=instructions)

    return self._proto_step_result(inv, step_name)

  def query_test_result_statistics(self,
                                   res,
                                   step_name='query_test_result_statistics'):
    """Emulates query_test_result_statistics() return value.

    Args:
        res (proto.v1.resultdb.QueryTestResultStatisticsResponse object): the
          response to simulate.
        step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def upload_invocation_artifacts(self, res,
                                  step_name='upload_invocation_artifacts'):
    """Emulates upload_invocation_artifacts() return value.

    Args:
        res (proto.v1.resultdb.BatchCreateArtifactsResponse object): the
          response to simulate.
        step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_test_results(self, res, step_name='query_test_results'):
    """Emulates query_test_results() return value.

    Args:
      res (proto.v1.resultdb.QueryTestResultsResponse object): the response.
      step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_test_variants(self, res, step_name='query_test_variants'):
    """Emulates query_test_variants() return value.

    Args:
      res (proto.v1.resultdb.QueryTestVariantsResponse object): the response.
      step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_new_test_variants(self, res, step_name='query_new_test_variants'):
    """Emulates query_new_test_results() return value

    Args:
      res (proto.v1.resultdb.QueryNewtestVariantsResponse object): the response.
      step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def _proto_step_result(self, message, step_name):
    """Utility method that converts a proto into JSON-formatted step data."""
    res = json_format.MessageToDict(message)
    return self.step_data(
        step_name,
        self.m.json.output_stream(res),
    )
