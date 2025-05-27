# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Thin API for parsing semver strings into comparable object."""

# Keep the legacy behavior of falling back to less-strict version parsing.
from __future__ import annotations

import packaging_legacy.version

from recipe_engine.recipe_api import RecipeApi


class VersionApi(RecipeApi):

  @staticmethod
  def parse(version):
    """Parse implements PEP 440 parsing for semvers.

    If `version` is strictly parseable as PEP 440, this returns a Version
    object. Otherwise it does a 'loose' parse, just extracting numerals from
    version.

    You can read more about how this works at:
    https://setuptools.readthedocs.io/en/latest/pkg_resources.html#parsing-utilities
    (for strict parsing) and https://github.com/di/packaging_legacy (for the fallback
    behavior).
    """
    return packaging_legacy.version.parse(version)
