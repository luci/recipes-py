# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import base64

from google.protobuf import text_format as textpb

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.config_service.proto import (
    config_service as config_service_pb2,)


class LuciConfigTestApi(recipe_test_api.RecipeTestApi):

  def mock_config(self, project, config_name, data, nesting=None):
    """Mock a config returned by the luci-config API.

    Args:
        project (str): The LUCI project name.
        config_name (str): The name of the config file to mock, e.g.
            "commit-queue.cfg".
        data (str or protobuf): The mock data that should be returned.
            Either a string containing a textproto, or a protobuf object.
        nesting (str): Parent step under which this step is nested.
    """
    if not isinstance(data, str):
      data = textpb.MessageToString(data)
    step_name = f"fetch {project} {config_name}.get"
    if nesting:  # pragma: no cover
      step_name = f"{nesting}.{step_name}"
    return self.step_data(
        step_name,
        self.m.proto.output_stream(
            config_service_pb2.Config(raw_content=data.encode(),)),
    )

  def mock_local_config(self, project, config_name, data, nesting=None):
    """Mock a config read from disk.

    Args:
        project (str): The LUCI project name.
        config_name (str): The name of the config file to mock, e.g.
            "commit-queue.cfg".
        data (str or protobuf): The mock data that should be returned.
            Either a string containing a textproto, or a protobuf object.
        nesting (str): Parent step under which this step is nested.
    """
    if not isinstance(data, str):
      data = textpb.MessageToString(data)
    step_name = f"read {project} {config_name}"
    if nesting:  # pragma: no cover
      step_name = f"{nesting}.{step_name}"
    return self.step_data(step_name, self.m.file.read_text(data))
