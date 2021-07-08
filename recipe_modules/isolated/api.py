# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api


class IsolatedApi(recipe_api.RecipeApi):
  """API for interacting with isolated.

  The isolated client implements a tar-like scatter-gather mechanism for
  archiving files. The tool's source lives at
  http://go.chromium.org/luci/client/cmd/isolated.

  This module will deploy the client to [CACHE]/isolated_client/; users should
  add this path to the named cache for their builder.
  """

  def __init__(self, isolated_properties, *args, **kwargs):
    super(IsolatedApi, self).__init__(*args, **kwargs)
    self._server = isolated_properties.get('server', None)
    self._namespace = isolated_properties.get('namespace', 'default-gzip')

  def initialize(self):
    if self._test_data.enabled:
      self._server = 'https://example.isolateserver.appspot.com'

  @property
  def isolate_server(self):
    """Returns the associated isolate server."""
    assert self._server
    return self._server

  @property
  def namespace(self):
    """Returns the associated namespace."""
    assert self._namespace
    return self._namespace
