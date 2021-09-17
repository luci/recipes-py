# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import json_format

from recipe_engine import recipe_test_api

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
        self.m.raw_io.stream_output(common.serialize(inv_bundle)),
    )

  def get_test_result_history(self, res, step_name='get_test_result_history'):
    """Emulates get_test_result_history() return value.

    Args:
        res (proto.v1.resultdb.GetTestResultHistoryResponse object): the
          response to simulate.
        step_name (str): the name of the step to simulate.
    """
    return self._proto_step_result(res, step_name)

  def query_test_result_statistics(self, res,
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

  def _proto_step_result(self, message, step_name):
    """Utility method that converts a proto into JSON-formatted step data."""
    res = json_format.MessageToDict(message)
    return self.step_data(
        step_name,
        self.m.raw_io.stream_output(json.dumps(res)),
    )
