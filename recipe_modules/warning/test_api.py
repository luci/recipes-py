# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows recipe modules to issue warnings in test definitions."""

from recipe_engine import recipe_api, recipe_test_api


class WarningApi(recipe_test_api.RecipeTestApi):
  def issue(self, name):  # pragma: no cover
    """Issues an execution warning.

    `name` MAY either be a fully qualified "repo_name/WARNING_NAME" or a short
    "WARNING_NAME". If it's a short name, then the "repo_name" will be
    determined from the location of the file issuing the warning (i.e. if the
    issue() comes from a file in repo_X, then "WARNING_NAME" will be
    transformed to "repo_X/WARNING_NAME").

    It is recommended to use the short name if the warning is defined in the
    same repo as the issue() call.
    """
    recipe_api.record_execution_warning(name, 1)  # pragma: no cover
