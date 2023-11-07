# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows recipe modules to issue warnings in simulation test."""

import inspect

from recipe_engine import recipe_api


class WarningApi(recipe_api.RecipeApi):
  warning_client = recipe_api.RequireClient('warning')

  @recipe_api.escape_all_warnings
  def issue(self, name):
    """Issues an execution warning.

    `name` MAY either be a fully qualified "repo_name/WARNING_NAME" or a short
    "WARNING_NAME". If it's a short name, then the "repo_name" will be
    determined from the location of the file issuing the warning (i.e. if the
    issue() comes from a file in repo_X, then "WARNING_NAME" will be
    transformed to "repo_X/WARNING_NAME").

    It is recommended to use the short name if the warning is defined in the
    same repo as the issue() call.
    """
    if self._test_data.enabled: # pragma: no cover
      issuer_frame, issuer_file, _, _, _, _ = inspect.stack()[1]
      try:
        fq_name = self.warning_client.resolve_warning(name, issuer_file)
        # Escapes the function that issues the warning so that we can attribute
        # call site to the caller of that function.
        self.warning_client.escape_frame_function(fq_name, issuer_frame)
      finally:
        del issuer_frame
      self.warning_client.record_execution_warning(fq_name)
