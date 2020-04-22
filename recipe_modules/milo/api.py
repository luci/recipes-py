# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for specifying Milo behavior."""

import re

from google import protobuf
from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class MiloApi(recipe_api.RecipeApi):
  """A module for interacting with Milo."""

  def show_blamelist_for(self, gitiles_commits):
    """Specifies which commits and repos Milo should show a blamelist for.

    If not set, Milo will only show a blamelist for the main repo in which this
    build was run.

    Args:
      gitiles_commits: A list of buildbucket.common_pb2.GitilesCommit messages
        or dicts of the same structure.
        Each commit must have host, project and id.
        ID must match r'^[0-9a-f]{40}$' (git revision).
    """
    gitiles_commits = [_as_msg(c, common_pb2.GitilesCommit)
                       for c in gitiles_commits]
    # Validate commit object.
    for c in gitiles_commits:
      assert isinstance(c, common_pb2.GitilesCommit), c

      assert c.host
      assert '/' not in c.host, c.host

      assert c.project
      assert not c.project.startswith('/'), c.project
      assert not c.project.startswith('a/'), c.project
      assert not c.project.endswith('/'), c.project

      assert re.match('^[0-9a-f]{40}$', c.id), c.id

      # position is uint32
      # Does not need extra validation.

    # The fact that it sets a property value is an implementation detail.
    res = self.m.step('set blamelist pins', cmd=None)
    prop_name = '$recipe_engine/milo/blamelist_pins'
    res.presentation.properties[prop_name] = [
        json_format.MessageToDict(c) for c in gitiles_commits]


def _as_msg(value, typ):
  """Converts a dict to the specified proto type if necessary.

  Allows functions to accept either proto messages or dicts of the same
  structure."""
  assert isinstance(value, (dict, protobuf.message.Message)), type(value)
  if isinstance(value, dict):
    value = typ(**value)
  return value
