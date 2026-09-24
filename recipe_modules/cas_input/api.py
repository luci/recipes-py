# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Simple API for handling CAS inputs to a recipe.

Recipes sometimes need files as part of their execution which don't live in
source control (for example, they're generated elsewhere but tested in the
recipe). In that case, there needs to be an easy way to give these files as an
input to a recipe, so that the recipe can use them somehow. This module makes
this easy.

This module has input properties which contains a list of CAS inputs to
download. These can easily be download to disk with the 'download_caches'
method, and subsequently used by a recipe in whatever relevant manner.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from PB.recipe_modules.recipe_engine.cas_input import properties as properties_pb
from recipe_engine import config_types

from RECIPE_MODULES.recipe_engine import cas_input

from recipe_engine import recipe_api


class CasInputApi(recipe_api.RecipeApi):
  """A module for downloading CAS inputs to a recipe."""

  m: cas_input.DEPS

  def __init__(self, props: properties_pb.InputProperties, **kwargs: Any) -> None:
    super().__init__(**kwargs)

    self._module_props = props

  @property
  def input_caches(self) -> Sequence[properties_pb.CasCache]:
    return self._module_props.caches

  def download_caches(
      self,
      output_dir: config_types.Path,
      caches: Sequence[properties_pb.CasCache] | None = None,
  ) -> None:
    """Downloads RBE-CAS caches and puts them in a given directory.

    Args:
      output_dir: The output directory to download the caches to. If you're
        unsure of what directory to use, self.m.path.start_dir is a directory
        the recipe engine sets up for you that you can use.
      caches: A CasCache proto message containing the caches which should be
        downloaded. See properties.proto for the message definition.
        If unset, it uses the caches in this recipe module properties.
    Returns:
      The output directory as a Path object which contains all the cache data.
    """
    if not caches:
      caches = self.input_caches

    for cache in caches:
      cache_out = output_dir
      if cache.local_relpath:
        cache_out = cache_out / cache.local_relpath
      self.m.cas.download("download cache", cache.digest, cache_out)

    return output_dir
