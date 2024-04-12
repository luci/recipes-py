# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations
from dataclasses import dataclass

from typing import TYPE_CHECKING

from recipe_engine import recipe_test_api
from recipe_engine.config_types import CheckoutBasePath, Path, ResolvedBasePath

# Avoid circular import.
if TYPE_CHECKING:  # pragma: no cover
  from .api import NamedBasePathsType


@dataclass(frozen=True)
class UnvalidatedPath:
  base: str
  pieces: tuple[str, ...]

  def join(self, *pieces: str) -> UnvalidatedPath:
    return UnvalidatedPath(self.base, self.pieces + pieces)


class PathTestApi(recipe_test_api.RecipeTestApi):

  def exists(self, *paths: Path):
    """This is an alias for `files_exist`."""
    return self.files_exist(*paths)

  @recipe_test_api.mod_test_data
  @staticmethod
  def files_exist(*paths: Path | UnvalidatedPath):
    """This mocks the path module to believe that the given `paths` exist as
    FILES prior to the start of the recipe.

    To mock the existence of paths which are generated DURING the execution of
    the recipe, use recipe_engine/path.mock_* functions.

    This sets the type of paths to be 'FILE'. If you want to mock the existence
    of a directory, use dirs_exist().
    """
    assert all(isinstance(p, (Path, UnvalidatedPath)) for p in paths)
    return list(paths)

  @recipe_test_api.mod_test_data
  @staticmethod
  def dirs_exist(*paths: Path | UnvalidatedPath):
    """This mocks the path module to believe that the given `paths` exist as
    DIRECTORIES prior to the start of the recipe.

    To mock the existence of paths which are generated DURING the execution of
    the recipe, use recipe_engine/path.mock_* functions.

    This sets the type of paths to be 'DIRECTORY'. If you want to mock the
    existence of a file, use exists().
    """
    assert all(isinstance(p, (Path, UnvalidatedPath)) for p in paths)
    return list(paths)

  def __getitem__(self, name: NamedBasePathsType) -> Path:
    """This gets a Path based on `name` for passing to the `exists`,
    `files_exist` or `dirs_exist` methods on this test API.

    DEPRECATED: Use the following @properties on this module instead:
      * start_dir
      * tmp_base_dir
      * cache_dir
      * cleanup_dir
      * home_dir
      * checkout_dir (but use of checkout_dir is generally discouraged - just
      pass the Paths around instead of using this global variable).
    """
    match name:
      case 'cache':
        return self.cache_dir
      case 'cleanup':
        return self.cleanup_dir
      case 'home':
        return self.home_dir
      case 'start_dir':
        return self.start_dir
      case 'tmp_base':
        return self.tmp_base_dir
      case 'checkout':
        return self.checkout_dir

    # Avoid circular import.
    from .api import PathApi  # pragma: no cover
    if name not in PathApi.NamedBasePaths:  # pragma: no cover
      raise ValueError(
          f'Unknown base path {name!r} - allowed names are {PathApi.NamedBasePaths!r}'
      )

  @property
  def start_dir(self) -> Path:
    return Path(ResolvedBasePath('[START_DIR]'))

  @property
  def tmp_base_dir(self) -> Path:
    return Path(ResolvedBasePath('[TMP_BASE]'))

  @property
  def cache_dir(self) -> Path:
    return Path(ResolvedBasePath('[CACHE]'))

  @property
  def cleanup_dir(self) -> Path:
    return Path(ResolvedBasePath('[CLEANUP]'))

  @property
  def home_dir(self) -> Path:
    return Path(ResolvedBasePath('[HOME]'))

  @property
  def checkout_dir(self) -> Path:
    return Path(CheckoutBasePath())

  def cast_to_path(self, strpath: str) -> UnvalidatedPath:
    """Allows an absolute path to be used to mock the existence.

    This path will be validated to be absolute by the path module when it loads
    the mocked data. This will validate and split `strpath` according to the
    mocked OS (e.g. using '\\' and '/' and parsing Windows drive on Windows,
    using '/' on *nix).

    These paths are ONLY good for .exists, .files_exist and .dirs_exist on this
    test API.
    """
    return UnvalidatedPath(strpath, ())
