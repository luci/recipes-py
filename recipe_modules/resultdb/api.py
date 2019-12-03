# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the ResultDB service.

Requires `rdb` command in `$PATH`:
https://godoc.org/go.chromium.org/luci/resultdb/cmd/rdb
"""

from recipe_engine import recipe_api


class ResultDBAPI(recipe_api.RecipeApi):
  """A module for interacting with ResultDB."""

  HOST_PROD = 'results.api.cr.dev'

  def initialize(self):
    self._host = (
        self.m.buildbucket.build.infra.resultdb.hostname or self.HOST_PROD
    )

  @property
  def host(self):
    """Hostname of ResultDB to use in API calls.

    Defaults to the hostname of the current build's invocation.
    """
    return self._host
