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

  def config_test_presentation(self, column_keys=(), grouping_keys=('status',)):
    """Specifies how the tests should be rendered.

    Args:
      column_keys:
        A list of keys that will be rendered as 'columns'. status is always the
        first column and name is always the last column (you don't need to
        specify them). A key must be one of the following:
        1. 'v.{variant_key}': variant.def[variant_key] of the test variant (e.g.
          v.gpu).

      grouping_keys:
        A list of keys that will be used for grouping tests. A key must be one
        of the following:
        1. 'status': status of the test variant.
        2. 'name': name of the test variant.
        3. 'v.{variant_key}': variant.def[variant_key] of the test variant (e.g.
        v.gpu).
        Caveat: test variants with only expected results are not affected by
        this setting and are always in their own group.
    """

    # Validate column_keys.
    for k in column_keys:
      assert k.startswith('v.')

    # Validate grouping_keys.
    for k in grouping_keys:
      assert k in ['status', 'name'] or k.startswith('v.')

    # The fact that it sets a property value is an implementation detail.
    res = self.m.step('set test presentation config', cmd=None)
    prop_name = '$recipe_engine/milo/test_presentation'
    res.presentation.properties[prop_name] = {
      'column_keys': column_keys,
      'grouping_keys': grouping_keys,
    }

def _as_msg(value, typ):
  """Converts a dict to the specified proto type if necessary.

  Allows functions to accept either proto messages or dicts of the same
  structure."""
  assert isinstance(value, (dict, protobuf.message.Message)), type(value)
  if isinstance(value, dict):
    value = typ(**value)
  return value
