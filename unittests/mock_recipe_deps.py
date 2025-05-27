# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides a 'mock' version of the RecipeDeps object.

This is very lightweight and should be used for testing recipe_engine
functionality when you don't need to use actual recipe or recipe module code.

Access this via test_env.RecipeEngineUnitTest.MockRecipeDeps().

NOTE: This only contains constructs which are sufficient for the existing tests.
Lots of APIs are missing from these, and you should feel free to extend these
mocks.

Since these mocks are typically passed directly to recipe_engine functions in
lieu of the real RecipeDeps, please try not to add too many APIs here which
don't exist on the real objects (i.e. "path helpers" or things of that nature).
"""


from __future__ import annotations

import sys
import os

from recipe_engine.internal.recipe_deps import parse_deps_spec


class MockRecipeDeps:
  """A mock version of recipe_deps.RecipeDeps."""

  def __init__(self, modules_to_deps=None, recipes_to_deps=None):
    """Creates a MockRecipeDeps with a single 'main' repo containing the modules
    and recipes specified by modules_to_deps and recipes_to_deps.

    Args:
      * modules_to_deps (None|Dict[str, DEPS specification]) - Passed to the
        main_repo (MockRecipeRepo). Maps available recipe modules (by name)
        to their DEPS specification.
      * recipes_to_deps (None|Dict[str, DEPS specification]) - Passed to the
        main_repo (MockRecipeRepo). Maps available recipes (by name)
        to their DEPS specification.
    """
    self.main_repo_id = 'main'
    self.main_repo = MockRecipeRepo(
        self, 'main', modules_to_deps or {}, recipes_to_deps or {})
    self.repos = {'main': self.main_repo}

  def add_repo(self, name, modules_to_deps=None, recipes_to_deps=None):
    """Creates and adds an additional repo to the MockRecipeDeps.

    This will be available in `.repos`, and can be referred to in DEPS entries
    of other repos currently in this MockRecipeDeps.

    Args:
      * name (str) - The name of the repo to add.
      * modules_to_deps (None|Dict[str, DEPS specification]) - Passed to the
        repo (MockRecipeRepo). Maps available recipe modules (by name)
        to their DEPS specification.
      * recipes_to_deps (None|Dict[str, DEPS specification]) - Passed to the
        repo (MockRecipeRepo). Maps available recipes (by name)
        to their DEPS specification.
    """
    self.repos[name] = MockRecipeRepo(
        self,
        name,
        modules_to_deps or {},
        recipes_to_deps or {}
    )

class MockRecipeRepo:
  """A mock version of recipe_deps.RecipeRepo."""

  def __init__(self, rdeps, name, modules_to_deps, recipes_to_deps):
    """Creates a MockRecipeRepo with the name `name` containing the
    modules and recipes specified by modules_to_deps and recipes_to_deps.

    NOTE: You shouldn't call this directly, but instead use
    `MockRecipeDeps.add_repo`.

    Args:
      * rdeps (MockRecipeDeps) - The MockRecipeDeps that this repo belongs to.
      * name (str) - The name of this repo.
      * modules_to_deps (None|Dict[str, DEPS specification]) - Maps available
        recipe modules (by name) to their DEPS specification.
      * recipes_to_deps (None|Dict[str, DEPS specification]) - Maps available
        recipes (by name) to their DEPS specification.
    """
    self.recipe_deps = rdeps
    self.name = name
    if sys.platform.startswith('win'):
      self.path = 'c:\\%s_ROOT\\' % name.upper()
    else:
      self.path = '/%s_ROOT/' % name.upper()
    self.modules = {
      module_name: MockRecipeModule(self, module_name, DEPS)
      for module_name, DEPS in modules_to_deps.items()
    }
    self.recipes = {
      recipe_name: MockRecipe(self, recipe_name, DEPS)
      for recipe_name, DEPS in recipes_to_deps.items()
    }

class MockRecipeModule:
  """A mock version of recipe_deps.RecipeModule."""

  def __init__(self, repo, name, DEPS):
    """Creates a MockRecipeModule with the given name and DEPS spec.

    Args:
      * repo (MockRecipeRepo) - The MockRecipeRepo that this recipe belongs to.
      * name (str) - The name of the recipe module.
      * DEPS (List[str]|Dict[str, str]) - A valid DEPS spec, as understood by
       recipe_deps.parse_deps_spec().
    """
    self.repo = repo
    self.name = '%s/%s' % (repo.name, name)
    self.path = os.path.join(repo.path, 'recipe_modules', name)
    # pylint: disable=invalid-name
    self.normalized_DEPS = parse_deps_spec(repo.name, DEPS)

class MockRecipe:
  """A mock version of recipe_deps.Recipe."""

  def __init__(self, repo, name, DEPS):
    """Creates a MockRecipe with the given name and DEPS spec.

    Args:
      * repo (MockRecipeRepo) - The MockRecipeRepo that this recipe belongs to.
      * name (str) - The name of the recipe. Note that this allows for
        'modname:tests/name' type names as well.
      * DEPS (List[str]|Dict[str, str]) - A valid DEPS spec, as understood by
       recipe_deps.parse_deps_spec().
    """
    self.repo = repo
    self.path = os.path.join(repo.path, 'recipes', name) + '.py'
    self.resources_dir = os.path.join(repo.path, 'recipes', name) + '.resources'
    # pylint: disable=invalid-name
    self.normalized_DEPS = parse_deps_spec(repo.name, DEPS)
