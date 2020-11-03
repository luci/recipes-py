# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for Tricium analyzers to use."""

from collections import namedtuple
from google.protobuf import json_format

from PB.tricium.data import Data

from recipe_engine import recipe_api
from recipe_engine.config_types import Path


class TriciumApi(recipe_api.RecipeApi):
  """TriciumApi provides basic support for Tricium."""

  def __init__(self, **kwargs):
    """Sets up the API.

    This assumes that the input is a Tricium GitFileDetails
    object, and the output is a Tricium Results object (see
    https://chromium.googlesource.com/infra/infra/+/master/go/src/infra/tricium/api/v1/data.proto
    for details and definitions).
    """
    super(TriciumApi, self).__init__(**kwargs)
    self._comments = []

  def add_comment(self,
                  category,
                  message,
                  path,
                  start_line=0,
                  end_line=0,
                  start_char=0,
                  end_char=0,
                  suggestions=()):
    comment = Data.Comment()
    comment.category = category
    comment.message = message
    comment.path = path
    comment.start_line = start_line
    comment.end_line = end_line
    comment.start_char = start_char
    comment.end_char = end_char
    for s in suggestions:
      # Convert from dict to proto message by way of JSON.
      json_format.Parse(self.m.json.dumps(s), comment.suggestions.add())

    if comment not in self._comments:
      self._comments.append(comment)

  def write_comments(self):
    result = self.m.step('write results', [])
    results_msg = Data.Results()
    results_msg.comments.extend(self._comments)
    result.presentation.properties['tricium'] = json_format.MessageToJson(
        results_msg)
