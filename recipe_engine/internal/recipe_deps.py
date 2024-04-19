# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Contains all logic related to the management of recipe dependencies.

The classes in this module form a hierarchy:

  RecipeDeps
    RecipeRepo
      Recipe
      RecipeModule
        Recipe

RecipeDeps - Manages the entire `.recipe_deps` folder, which includes bringing
  all dependencies up to date (with git), and also loading those repos (finding
  all recipes and recipe modules in them).

RecipeRepo - The files from a single recipe repository. This object exists after
  all git operations have been finished, and forms the interface for a single
  recipe repository.

RecipeModule - Represents a single recipe module. These can contain recipes. The
  recipes they contain are also visible on their containing repository.

Recipe - Represents a single recipe.


The RecipeModule and Recipe objects will not import code from disk until you
call one of their appropriate methods (e.g. `do_import` or `global_symbols`,
respectively).

All DEPS evaluation is also handled in this file.
"""

import bdb
import importlib
import inspect
import logging
import os
import re
import sys

from functools import cached_property
from typing import Type

from future.utils import raise_

import attr

from attr.validators import optional

from google.protobuf import json_format as jsonpb

from ..config_types import Path, ResolvedBasePath
from ..engine_types import freeze, FrozenDict
from ..recipe_api import UnresolvedRequirement, RecipeScriptApi, BoundProperty
from ..recipe_api import RecipeApi
from ..recipe_test_api import RecipeTestApi, BaseTestData, DisabledTestData

from . import fetch
from . import proto_support
from . import dev_support

from .attr_util import attr_type, attr_value_is, attr_superclass, attr_dict_type
from .exceptions import CyclicalDependencyError, UnknownRecipe, UnknownRepoName
from .exceptions import RecipeLoadError, RecipeSyntaxError, MalformedRecipeError
from .exceptions import MalformedModuleError, UnknownRecipeModule
from .simple_cfg import SimpleRecipesCfg, RECIPES_CFG_LOCATION_REL
from .test.test_util import filesystem_safe
from .warn.definition import (parse_warning_definitions,
                              RECIPE_WARNING_DEFINITIONS_REL)


LOG = logging.getLogger(__name__)

# Subdirectories of a recipe module that may contain recipes.
MODULE_RECIPE_SUBDIRS = ('tests', 'examples', 'run')


@attr.s(frozen=True)
class RecipeDeps:
  """Holds all of the dependency repos for the current recipe execution.

  If no '-O' override options were passed on the command line, you'll see a 1:1
  mapping of repo names here and the subfolders of the `.recipe_deps` folder
  that the engine creates in your repo (hence the name of this class).
  """

  # The mapping of repo_name -> RecipeRepo for all known repos.
  repos = attr.ib(converter=freeze)  # type: dict[str, RecipeRepo]
  @repos.validator
  def check(self, attrib, value):
    # This is a separate function (as opposed to the `validator=` kwarg),
    # to avoid need for forward declaration of `RecipeRepo`.
    attr_type(FrozenDict)(self, attrib, value)
    attr_dict_type(str, RecipeRepo)(self, attrib, value)

  # The repo_name for the 'entry point' repo for the current process. All
  # recipe names on the command line will be resolved relative to this repo, and
  # this repo's recipes_cfg is the one that the engine loaded to create this
  # RecipeDeps.
  #
  # This repo is guaranteed to be a member of `repos`.
  main_repo_id = attr.ib(validator=attr_type(str))  # type: str

  def __attrs_post_init__(self):
    def _raise_unknown_rname(repo_name):
      raise UnknownRepoName(
        'No repo with repo_name {repo_name!r}. Add it to recipes.cfg?'.
        format(repo_name=repo_name))
    self.repos.on_missing = _raise_unknown_rname

  @property
  def main_repo(self):
    """Returns the RecipeRepo corresponding to the main repo name."""
    return self.repos[self.main_repo_id]

  @cached_property
  def recipe_deps_path(self):
    """Returns the location of the .recipe_deps directory."""
    return os.path.join(self.main_repo.recipes_root_path, '.recipe_deps')

  @cached_property
  def previous_test_failures_path(self):
    """Returns the location of the .previous_failures file."""
    return os.path.join(self.recipe_deps_path, '.previous_test_failures')

  @cached_property
  def warning_definitions(self):
    """Returns warning definitions for all repos in this RecipeDeps.

    Key is fully-qualified warning name (i.e. `$repo_name/WARNING_NAME`).
    """
    return {
        '/'.join((repo_name, warning_name)) : definition
        for repo_name, repo in self.repos.items()
        for warning_name, definition in repo.warning_definitions.items()
    }

  @classmethod
  def create(cls, main_repo_path, overrides, proto_override,
             minimal_protoc=False):
    """Creates a RecipeDeps.

    This will possibly do network operations to fetch recipe repos from git if
    the main repo depends on other repos which are not in overrides.

    Args:
      * main_repo_path (str) - Absolute path to the root of the main (entry
        point) repo. This repo determines (via its recipes.cfg file) what other
        dependency repos are fetched, as well as what namespace we use to
        resolve recipe names to run.
      * overrides (Dict[str, str]) - A map of repo_name to absolute path to
        the root of the repo which should be used to satisfy this dependency.
      * proto_override (None|str) - The path to the compiled protobuf tree (if
        any).
      * minimal_protoc (bool) - If True, skips all proto compiliation. This is used
        for subcommands (like manual_roll) where we don't need this, and it can
        actively interfere with the subcommand's functionality.

    Returns a RecipeDeps.
    """
    simple_cfg = SimpleRecipesCfg.from_json_file(
      os.path.join(main_repo_path, RECIPES_CFG_LOCATION_REL))

    extra = set(overrides) - set(simple_cfg.deps)
    if extra:
      raise ValueError(
        'attempted to override %r, which do not appear in recipes.cfg' %
        (extra,))

    # A bit hacky; RecipeRepo objects have a backreference to the RecipeDeps, so
    # we have to create it first.
    ret = cls({}, simple_cfg.repo_name)

    # Check that our repo doesn't depend on itself.
    if ret.main_repo_id in simple_cfg.deps:
      raise RecipeLoadError('recipes.cfg: cannot depend on self (repo %r)' % (
        (ret.main_repo,)))

    repos = {}
    main_backend = None
    if os.path.isdir(os.path.join(main_repo_path, '.git')):
      main_backend = fetch.GitBackend(main_repo_path, None)
    repos[ret.main_repo_id] = RecipeRepo.create(
      ret, main_repo_path, simple_cfg=simple_cfg, backend=main_backend)

    for project_id, path in overrides.items():
      backend = None
      if os.path.isdir(os.path.join(path, '.git')):
        backend = fetch.GitBackend(path, None)
      repos[project_id] = RecipeRepo.create(ret, path, backend=backend)

    recipe_deps_path = os.path.join(
      main_repo_path,
      simple_cfg.recipes_path,
      '.recipe_deps'
    )
    for repo_name, dep in simple_cfg.deps.items():
      if repo_name in repos:
        continue

      dep_path = os.path.join(recipe_deps_path, repo_name)
      backend = fetch.GitBackend(dep_path, dep.url)
      backend.checkout(dep.branch, dep.revision)
      repos[repo_name] = RecipeRepo.create(ret, dep_path, backend=backend)

      # Assert that any dependencies of `repo_name` are included (by name) in
      # our own simple_cfg. Otherwise the transitive dependency set is not
      # specified here, which is an error.
      #
      # Additionally, catch if one of the missing dependencies is a reference
      # to our own repo!
      missing_deps = set(repos[repo_name].simple_cfg.deps)
      missing_deps.difference_update(simple_cfg.deps)
      if ret.main_repo_id in missing_deps:
        raise RecipeLoadError(
            'recipes.cfg: Dependency %r has circular dependency on %r' %
            (repo_name, ret.main_repo_id))

      if missing_deps:
        raise RecipeLoadError(
            'recipes.cfg: Repo %r depends on %r, which %s missing' %
            (repo_name, sorted(missing_deps),
             ('is' if len(missing_deps) == 1 else 'are')))

    # This makes `repos` unmodifiable. object.__setattr__ is needed to get
    # around attrs' frozen attributes.
    repos = freeze(repos)
    repos.on_missing = ret.repos.on_missing
    object.__setattr__(ret, 'repos', repos)

    protoc_deps = ret
    if minimal_protoc:
      protoc_deps = RecipeDeps(
          {'recipe_engine': ret.repos['recipe_engine'], },
          'recipe_engine',
      )

    proto_support.append_to_syspath(
        proto_support.ensure_compiled(protoc_deps, proto_override))

    # Add the _venv link, if we can.
    dev_support.ensure_venv(ret)

    return ret


@attr.s(frozen=True)
class RecipeRepo:
  """This represents a 'recipe repo', i.e. a folder on disk which contains all
  of the requirements of a recipe repo:
    * an infra/config/recipes.cfg file
    * a `recipes` and/or `recipe_modules` folder
    * a recipes.py script

  A RecipeRepo may or MAY NOT be a git repo. If the RecipeRepo is a git repo,
  the `backend` field will be populated with a GitBackend instance. Once
  a RecipeRepo is constructed, nothing should assume that any git write
  operations are available (i.e. all network fetches, checkout, clean, etc. have
  already been done).
  """

  recipe_deps = attr.ib(validator=attr_type(RecipeDeps))  # type: RecipeDeps

  # Absolute path to the root of this repository.
  path = attr.ib(validator=[
    attr_type(str),
    attr_value_is('an absolute path', os.path.isabs),
  ])  # type: str

  # The SimpleRecipesCfg for this repo.
  simple_cfg = attr.ib(
      validator=attr_type(SimpleRecipesCfg)
  )  # type: SimpleRecipesCfg

  # Mapping of module name -> RecipeModule for all recipe modules in this repo.
  modules = attr.ib(converter=freeze)  # type: dict[str, RecipeModule]
  @modules.validator
  def check(self, attrib, value):
    # This is a separate function (as opposed to the `validator=` kwarg),
    # to avoid need for forward declaration of `RecipeModule`.
    attr_type(FrozenDict)(self, attrib, value)
    attr_dict_type(str, RecipeModule)(self, attrib, value)

  # Mapping of recipe name -> Recipe for all recipes in this repo.
  recipes = attr.ib(converter=freeze)  # type: dict[str, Recipe]
  @recipes.validator
  def check(self, attrib, value):
    # This is a separate function (as opposed to the `validator=` kwarg),
    # to avoid need for forward declaration of `Recipe`.
    attr_type(FrozenDict)(self, attrib, value)
    attr_dict_type(str, Recipe)(self, attrib, value)

  # The fetch.Backend, or None (if this repo was overridden on the command
  # line), for this repo.
  backend = attr.ib(
    validator=attr_type((type(None), fetch.Backend)))  # type: fetch.Backend

  def __attrs_post_init__(self):
    suffix = ' in repo {name!r}.'.format(name=self.name)
    def _raise_missing_module(module):
      raise UnknownRecipeModule(
        'No module named {module!r}'.format(module=module) + suffix)
    self.modules.on_missing = _raise_missing_module

    def _raise_missing_recipe(recipe):
      raise UnknownRecipe(
        'No recipe named {recipe!r}'.format(recipe=recipe) + suffix)
    self.recipes.on_missing = _raise_missing_recipe

  @cached_property
  def recipes_cfg_pb2(self):
    """Read recipes.cfg as a recipes_cfg_pb2.RepoSpec proto message.

    If successful, the return value is cached.
    """
    from PB.recipe_engine.recipes_cfg import RepoSpec
    recipes_cfg = os.path.join(self.path, RECIPES_CFG_LOCATION_REL)
    with open(recipes_cfg, 'rb') as cfg_file:
      return jsonpb.Parse(
          cfg_file.read(), RepoSpec(), ignore_unknown_fields=True)

  @cached_property
  def recipes_root_path(self):
    """The absolute path to the directory containing the `recipes`,
    `recipe_modules`, etc. directories."""
    # Normalize because self.simple_cfg.recipes_path is always POSIX-style.
    return os.path.normpath(
      os.path.join(self.path, self.simple_cfg.recipes_path))

  @cached_property
  def readme_path(self):
    """The absolute path for the 'README.recipes.md' file."""
    return os.path.join(self.recipes_root_path, 'README.recipes.md')

  @cached_property
  def warning_definitions(self):
    """The warnings defined (a dict of warning name to warning.Definition proto
    message) in this repo. Empty dict if not defined.
    """
    return parse_warning_definitions(os.path.join(
      self.recipes_root_path, RECIPE_WARNING_DEFINITIONS_REL))

  @property
  def name(self):
    """Shorthand for `RecipeRepo.simple_cfg.repo_name`."""
    return self.simple_cfg.repo_name

  @cached_property
  def sloppy_coverage_patterns(self):
    """Returns a frozenset of patterns (fnmatch absolute paths) for files which
    are covered in this repo by `DISABLE_STRICT_COVERAGE=True`."""
    patterns = []
    for mod in self.modules.values():
      if mod.uses_sloppy_coverage:
        patterns.append(os.path.join(mod.path, '*.py'))
    return frozenset(patterns)

  @cached_property
  def recipes_dir(self):
    """Returns the absolute path to this repo's recipes directory."""
    return os.path.join(self.recipes_root_path, 'recipes')

  @cached_property
  def modules_dir(self):
    """Returns the absolute path to this repo's recipe modules directory."""
    return os.path.join(self.recipes_root_path, 'recipe_modules')

  @property
  def expectation_paths(self):
    """Returns absolute paths to all expectation files.

    Includes even unused expectation files that don't have an associated
    test case or recipe.
    """

    # This can be replaced by glob.glob(..., recursive=True) in Python 3.
    def find_expectations(directory, pattern):
      regex = re.compile(pattern)
      for path, dirs, files in os.walk(
          os.path.abspath(directory), topdown=True):
        dirs[:] = [d for d in dirs if not d.endswith('.resources')]
        for basename in files:
          abspath = os.path.join(path, basename)
          relpath = os.path.relpath(abspath, directory)
          if regex.match(relpath):
            yield abspath

    paths = []
    sep = re.escape(os.path.sep)
    recipe_expectation_pattern = sep.join([
        # Recipes can lie at any nesting level.
        r'.+\.expected',
        # Expectation files must be in the root of a '*.expected' directory.
        r'[^%s]+\.json$' % sep,
    ])
    paths.extend(
        find_expectations(self.recipes_dir, recipe_expectation_pattern))
    paths.extend(
        find_expectations(
            self.modules_dir,
            sep.join([
                r'[^%s]+' % sep,
                r'(%s)' % r'|'.join(MODULE_RECIPE_SUBDIRS),
                recipe_expectation_pattern,
            ])))
    return paths

  @classmethod
  def create(cls, recipe_deps, path, backend=None, simple_cfg=None):
    """Creates a RecipeRepo.

    Args:
      * recipe_deps (RecipeDeps) - The RecipeDeps that this repo is part of.
      * path (str) - The path on disk where this recipe repo is checked out.
      * backend (None|fetch.Backend) - The git backend used to fetch this repo,
        if any. Overridden recipe repos will have this set to None.
      * simple_cfg (SimpleRecipesCfg) - If provided, will be taken as the
        SimpleRecipesCfg object for this repo. Only used as a minor optimization
        by RecipeDeps.create for the main repo to avoid parsing the file twice.

    Returns a RecipeRepo.
    """
    if not simple_cfg:
      simple_cfg = SimpleRecipesCfg.from_json_file(
        os.path.join(path, RECIPES_CFG_LOCATION_REL))

    # A bit hacky; Recipe and RecipeModule objects have a backreference to the
    # RecipeRepo, so we have to create it first.
    ret = cls(recipe_deps, path, simple_cfg, {}, {}, backend)

    modules = {}
    recipes = {}

    if not os.path.exists(ret.modules_dir):
      LOG.info('ignoring %r: does not exist', ret.modules_dir)
    elif not os.path.isdir(ret.modules_dir):
      LOG.warn('ignoring %r: not a directory', ret.modules_dir)
    else:
      for entry_name in os.listdir(ret.modules_dir):
        possible_mod_path = os.path.join(ret.modules_dir, entry_name)
        if not os.path.isdir(possible_mod_path):
          LOG.info('ignoring %r: not a directory', possible_mod_path)
        elif os.path.isfile(os.path.join(possible_mod_path, '__init__.py')):
          mod = RecipeModule.create(ret, entry_name)
          modules[entry_name] = mod
          for recipe in mod.recipes.values():
            recipes[recipe.name] = recipe
        else:
          # Only emit this log if the module directory is non-empty. If the
          # module directory is empty then it goes without saying that it will
          # be ignored. Ignore '__pycache__' subdirectories.
          for entry in os.scandir(possible_mod_path):
            if entry.name == '__pycache__':
              continue

            LOG.warn('ignoring %r: missing __init__.py', possible_mod_path)
            break

    for recipe_name in _scan_recipe_directory(ret.recipes_dir):
      recipes[recipe_name] = Recipe(
        ret,
        recipe_name,
        None,
      )

    # This makes `modules` and `recipes` unmodifiable. object.__setattr__ is
    # needed to get around attrs' frozen attributes.
    recipes = freeze(recipes)
    recipes.on_missing = ret.recipes.on_missing
    object.__setattr__(ret, 'recipes', recipes)
    modules = freeze(modules)
    modules.on_missing = ret.modules.on_missing
    object.__setattr__(ret, 'modules', modules)

    return ret


@attr.s(frozen=True)
class RecipeModule:
  repo = attr.ib(validator=attr_type(RecipeRepo))  # type: RecipeRepo
  name = attr.ib(validator=attr_type(str))

  # Maps from all recipe names under this module to the Recipe object.
  #
  # Note: the names of these will be e.g. `examples\full`. Use the Recipe's
  # .name field to get the repo-importable name `module:examples\full`.
  recipes = attr.ib(converter=freeze)
  @recipes.validator
  def check(self, attrib, value):
    # This is a separate function (as opposed to the `validator=` kwarg),
    # to avoid need for forward declaration of `Recipe`.
    attr_type(FrozenDict)(self, attrib, value)
    attr_dict_type(str, Recipe)(self, attrib, value)

  def __attrs_post_init__(self):
    def _raise_missing_recipe(recipe):
      raise UnknownRecipe(
        'No such recipe {recipe!r} in module {module!r} in repo {repo!r}.'.
        format(recipe=recipe, module=self.name, repo=self.repo.name))
    self.recipes.on_missing = _raise_missing_recipe

  @cached_property
  def full_name(self):
    """The fully qualified name of the recipe module (e.g. `repo/module`)."""
    return '%s/%s' % (self.repo.name, self.name)

  @cached_property
  def path(self):
    """The absolute path to the directory for this recipe module."""
    return os.path.join(self.repo.modules_dir, self.name)

  @cached_property
  def relpath(self):
    """The path to the directory for this recipe module relative to the repo
    root."""
    return os.path.relpath(self.path, self.repo.path)

  @cached_property
  def normalized_DEPS(self):
    """Returns a normalized form of the DEPS specification for this object.

    The normalized form looks like:

       {"local_name": ("repo_name", "module_name")}

    This imports the module code.
    """
    DEPS = getattr(self.do_import(), 'DEPS', ())
    return parse_deps_spec(self.repo.name, DEPS)

  @cached_property
  def transitive_DEPS(self):
    """Returns the set of fully-qualified DEPS reachable from this module."""
    ret = set()
    d = self.repo.recipe_deps
    for repo_name, module_name in self.normalized_DEPS.values():
      ret.add('%s/%s' % (repo_name, module_name))
      ret.update(d.repos[repo_name].modules[module_name].transitive_DEPS)
    return frozenset(ret)

  @cached_property
  def warnings(self):
    """Returns a tuple of warnings issued against this recipe module."""
    WARNINGS = getattr(self.do_import(), 'WARNINGS', ())
    return tuple(WARNINGS)

  @cached_property
  def _cumulative_import_warnings(self):
    """Returns all import warnings as a tuple that this module and its
    dependent modules hit. Each element of the tuple is a tuple of
    (fully-qualified warning name, importer RecipeModule).
    """
    return tuple(_collect_import_warnings(self))

  def do_import(self):
    """Imports the raw recipe module (i.e. python module).

    Does NOT instantiate the module's RecipeApi or RecipeTestApi classes.

    See module_importer.py for how RECIPE_MODULES importing works.

    Returns the raw imported python module for the given recipe module.
    """
    # note: see module_importer.py for this
    return importlib.import_module(
      'RECIPE_MODULES.%s.%s' % (self.repo.name, self.name))

  @cached_property
  def PROPERTIES(self):
    """Will return either a protobuf message, or an dictionary for config-style
    properties.

    When Config-style properties are gone, this should be removed.
    """
    properties_def = getattr(self.do_import(), 'PROPERTIES', {})
    if proto_support.is_message_class(properties_def):
      return properties_def

    # If PROPERTIES isn't a protobuf Message, it must be a legacy Property dict.
    # Let each property object know about the property name.
    full_decl_name = f'{self.repo.name}::{self.name}'
    return {
        prop_name: value.bind(prop_name, BoundProperty.MODULE_PROPERTY,
                              full_decl_name)
        for prop_name, value in properties_def.items()
    }

  @cached_property
  def TEST_API(self) -> Type[RecipeTestApi] | None:
    """Returns this module's TestApi subclass, if this recipe module has one.

    This will prefer an explicitly exported TEST_API object in the module's
    __init__ file, falling back to importing `test_api.py` and looking for
    a RecipeTestApi subclass.
    """
    imported_module = self.do_import()

    ret = getattr(imported_module, 'TEST_API', None)
    if ret:
      if issubclass(ret, RecipeTestApi):
        # This module explicitly exports TEST_API, return it.
        return ret
      raise MalformedModuleError(
          f'Module "{self.repo.name}/{self.name}" exports '
          'TEST_API which is not a subclass of RecipeTestApi.')

    # Fall back to finding the (optional) RecipeTestApi subclass.
    test_module = None
    if os.path.isfile(os.path.join(self.path, 'test_api.py')):
      test_module = importlib.import_module(
        f'RECIPE_MODULES.{self.repo.name}.{self.name}.test_api')

    if not test_module:
      return RecipeTestApi

    for v in test_module.__dict__.values():
      # If the recipe has literally imported the RecipeTestApi, we don't want
      # to consider that to be the real RecipeTestApi :)
      if v is RecipeTestApi:
        continue
      if inspect.isclass(v) and issubclass(v, RecipeTestApi):
        return v

    return RecipeTestApi

  @cached_property
  def API(self) -> Type[RecipeApi]:
    """Returns this module's RecipeApi subclass, which is required.

    This will prefer an explicitly exported API object in the module's
    __init__ file, falling back to importing `api.py` and looking for a
    RecipeApi subclass.

    Raises MalformedModuleError if an RecipeApi subclass was not found.
    """
    # Identify the RecipeApi subclass as this module's API.
    ret = getattr(self.do_import(), 'API', None)
    if ret:
      if issubclass(ret, RecipeApi):
        # This module explicitly explicitly exports API, return it.
        return ret
      raise MalformedModuleError(
          f'Module "{self.repo.name}/{self.name}" exports '
          'API which is not a subclass of RecipeApi.')

    # Fall back to trying to find it implicitly.
    api_module = importlib.import_module(
      f'RECIPE_MODULES.{self.repo.name}.{self.name}.api')

    for v in api_module.__dict__.values():
      # skip RecipeApi class
      if v is RecipeApi:
        continue

      if inspect.isclass(v) and issubclass(v, RecipeApi):
        return v

    raise MalformedModuleError(
        f'Recipe module "{self.repo.name}/{self.name}" is missing API.')

  @cached_property
  def CONFIG_CTX(self):
    # The current config system relies on implicitly importing all the
    # *_config.py files... ugh.
    for fname in os.listdir(self.path):
      if fname.endswith('_config.py'):
        importlib.import_module(
            f'RECIPE_MODULES.{self.repo.name}.{self.name}.{fname.strip(".py")}')

    # NOTE: late import for protobuf reasons
    from ..config import ConfigContext

    if CONFIG_CTX := getattr(self.do_import(), 'CONFIG_CTX', None):
      if not isinstance(CONFIG_CTX, ConfigContext):
        raise MalformedModuleError(
            'Module defines CONFIG_CTX but it is not an instance of ConfigContext?')
      return CONFIG_CTX

    # If CONFIG_CTX is not explicitly exported, try to discover it.... currently
    # this is ONLY used for `recipe_engine/path`.
    #
    # TODO(iannucci): fix recipe_engine/path to not use config.
    if os.path.isfile(os.path.join(self.path, 'config.py')):
      cfg_module = importlib.import_module(
          f'RECIPE_MODULES.{self.repo.name}.{self.name}.config')

      for v in cfg_module.__dict__.values():
        if isinstance(v, ConfigContext):
          return v

  @cached_property
  def uses_sloppy_coverage(self):
    """Returns True if this module has DISABLE_STRICT_COVERAGE set.

    This implies that ANY recipe code in the whole repo should count towards the
    coverage report on this module. This is the slowest way to do coverage
    calculation (especially for large modules), but there are still modules
    which have this set.

    crbug.com/693058,crbug.com/965278 - Get rid of this feature.
    """
    return getattr(self.do_import(), 'DISABLE_STRICT_COVERAGE', False)

  # TODO: py2 compat: Remove
  is_python_version_labeled = True
  python_version_compatibility = 'PY3'
  effective_python_compatibility = 'PY3'

  @classmethod
  def create(cls, repo, name):
    """Creates a RecipeModule.

    Args:
      * repo (RecipeRepo) - The recipe repo to which this module belongs.
      * name (str) - The name of this recipe module.

    Returns a RecipeModule.
    """
    # A bit hacky; Recipe objects have a backreference to the module, so we
    # have to create it first.
    ret = cls(repo, name, {})

    recipes = {}

    for subdir_name in MODULE_RECIPE_SUBDIRS:
      subdir = os.path.join(ret.path, subdir_name)
      if os.path.isdir(subdir):
        for recipe_name in _scan_recipe_directory(subdir):
          mod_scoped_name = '%s/%s' % (subdir_name, recipe_name)
          recipes[mod_scoped_name] = Recipe(
            repo,
            '%s:%s' % (name, mod_scoped_name),
            ret)

    # This makes `recipes` unmodifiable. object.__setattr__ is needed to get
    # around attrs' frozen attributes.
    recipes = freeze(recipes)
    recipes.on_missing = ret.recipes.on_missing
    object.__setattr__(ret, 'recipes', recipes)

    return ret


@attr.s(frozen=True)
class Recipe:
  # The repo in which this recipe is located.
  repo = attr.ib(validator=attr_type(RecipeRepo)) # type: RecipeRepo

  # The name of the recipe (e.g. `path/to/recipe` or 'module:run/recipe').
  name = attr.ib(validator=attr_type(str))

  # The RecipeModule, if any, to which this Recipe belongs.
  module = attr.ib(validator=optional(attr_type(RecipeModule)))

  def __attrs_post_init__(self):
    if self.module:
      if not self.name.startswith(self.module.name + ':'):
        raise ValueError(
            'recipe belongs to module {mod_name!r}, but does not start with'
            'module name: {recipe_name!r}'.format(
                mod_name=self.module.name, recipe_name=self.name))
    elif ':' in self.name:
      raise ValueError(
          'recipe name contains ":" but does not belong to a module: '
          '{recipe_name!r}'.format(recipe_name=self.name))

  @cached_property
  def path(self):
    """The absolute path of the recipe script."""
    native_name = self.name.replace('/', os.path.sep)
    if self.module:
      ret = os.path.join(self.module.path, native_name.split(':', 1)[1])
    else:
      ret = os.path.join(self.repo.recipes_dir, native_name)
    return ret + '.py'

  @cached_property
  def expectation_dir(self):
    """Returns the directory where this recipe's expectation JSON files live."""
    # TODO(iannucci): move expectation tree outside of the recipe tree.
    return os.path.splitext(self.path)[0] + '.expected'

  @cached_property
  def resources_dir(self):
    """Returns the directory where this recipe's resource files live."""
    return os.path.splitext(self.path)[0] + '.resources'

  @cached_property
  def relpath(self):
    """The path to the recipe relative to the repo root."""
    return os.path.relpath(self.path, self.repo.path)

  @cached_property
  def expectation_paths(self):
    """Get all existing expectation file paths for this recipe.

    Returns a set of absolute paths to all discovered expectation files.
    """
    ret = set()

    if os.path.isdir(self.expectation_dir):
      ret.update([
        os.path.join(self.expectation_dir, fname)
        for fname in os.listdir(self.expectation_dir)
        if fname.endswith('.json')
      ])

    return ret

  @cached_property
  def coverage_patterns(self):
    """Returns a frozenset of patterns (fnmatch absolute paths) for files which
    are covered by this recipe.

    Includes any sloppily covered files in this repo.
    """
    patterns = [self.path]
    if self.module:
      patterns.append(os.path.join(self.module.path, '*.py'))
    return self.repo.sloppy_coverage_patterns | frozenset(patterns)

  @cached_property
  def global_symbols(self):
    """Returns the global symbols for this recipe.

    This will exec the recipe's code (at most once) and return the dict
    containing all the recipe's global symbols (e.g. RunSteps, GenTests, etc.).

    This does NOT instantiate the recipe's DEPS or otherwise run the recipe.

    Returns a dictionary of names to python objects, as defined by the recipe
    script file.
    """
    recipe_globals = {}
    recipe_globals['__file__'] = self.path

    orig_path = sys.path[:]
    try:
      with open(self.path, 'rb') as f:
        exec(compile(f.read(), self.path, 'exec'), recipe_globals)
    except SyntaxError as ex:
      # Keep the SyntaxError details and traceback, but change the message from
      # 'invalid syntax'
      args = list(ex.args)
      args[0] = (
        "While loading recipe {recipe!r} in repo {repo!r}: {err}".format(
          recipe=self.name,
          repo=self.repo.name,
          err=ex,
        ))
      raise_(RecipeSyntaxError, tuple(args), sys.exc_info()[2])
    except bdb.BdbQuit:
      raise
    except Exception as ex:
      # Keep the error details and traceback, but change the message.
      args = list(ex.args or [''])
      args[0] = (
        "While loading recipe {recipe!r} in repo {repo!r}: {err!r}".format(
          recipe=self.name,
          repo=self.repo.name,
          err=ex,
        ))
      raise_(RecipeLoadError, tuple(args), sys.exc_info()[2])
    finally:
      sys.path = orig_path

    if 'RunSteps' not in recipe_globals:
      raise MalformedRecipeError(
          'Missing or misspelled RunSteps function in recipe %r.' % self.path)

    if 'GenTests' not in recipe_globals:
      raise MalformedRecipeError(
          'Missing or misspelled GenTests function in recipe %r.' % self.path)

    properties_def = recipe_globals.get('PROPERTIES', {})

    # If PROPERTIES isn't a protobuf Message, it must be a legacy Property dict.
    if not proto_support.is_message_class(properties_def):
      # Let each property object know about the fully qualified property name.
      recipe_globals['PROPERTIES'] = {
          name: value.bind(name, BoundProperty.RECIPE_PROPERTY, self.full_name)
          for name, value in properties_def.items()
      }

    return recipe_globals

  # TODO: py2 compat: Remove
  is_python_version_labeled = True
  python_version_compatibility = 'PY3'
  effective_python_compatibility = 'PY3'

  @cached_property
  def full_name(self):
    """The fully qualified name of the recipe (e.g. `repo::path/to/recipe`, or
    `repo::module:run/recipe`)."""
    return '%s::%s' % (self.repo.name, self.name)

  def gen_tests(self):
    """Runs this recipe's GenTests function.

    Yields all TestData fixtures for this recipe. Fills in the .expect_file
    property on each with an absolute path to the expectation file.
    """
    api = RecipeTestApi(module=None)
    resolved_deps = _resolve(
      self.repo.recipe_deps, self.normalized_DEPS, 'TEST_API', None, None)
    api.__dict__.update({
      local_name: resolved_dep
      for local_name, resolved_dep in resolved_deps.items()
      if resolved_dep is not None
    })
    for test_data in self.global_symbols['GenTests'](api):
      test_data.expect_file = os.path.join(
          self.expectation_dir, filesystem_safe(test_data.name),
      ) + '.json'
      yield test_data

  @cached_property
  def normalized_DEPS(self):
    """Returns a normalized form of the DEPS specification for this object.

    The normalized form looks like:

       {"local_name": ("repo_name", "module_name")}

    This reads the recipe code.
    """
    return parse_deps_spec(self.repo.name, self.global_symbols.get('DEPS', ()))

  @cached_property
  def transitive_DEPS(self):
    """Returns the set of fully-qualified DEPS reachable from this module."""
    ret = set()
    d = self.repo.recipe_deps
    for repo_name, module_name in self.normalized_DEPS.values():
      ret.add('%s/%s' % (repo_name, module_name))
      ret.update(d.repos[repo_name].modules[module_name].transitive_DEPS)
    return frozenset(ret)

  def mk_api(self, engine, test_data=None):
    """Makes a RecipeScriptApi, suitable for use with run_steps.

      * engine (RecipeEngine) - The engine to use for running.
      * test_data (RecipeTestData) - The test data to build the api with.

    Returns RecipeScriptApi.
    """
    test_data = test_data or DisabledTestData()

    api = RecipeScriptApi(
        test_data.get_module_test_data(None),
        Path(
            ResolvedBasePath.for_recipe_script_resources(
                test_data.enabled, self)),
        Path(ResolvedBasePath.for_bundled_repo(test_data.enabled, self.repo)),
    )
    resolved_deps = _resolve(
      self.repo.recipe_deps, self.normalized_DEPS, 'API', engine, test_data)
    for _, (warning, importer) in enumerate(_collect_import_warnings(self)):
      engine.record_import_warning(warning, importer)
    api.__dict__.update({
      local_name: resolved_dep
      for local_name, resolved_dep in resolved_deps.items()
      if resolved_dep is not None
    })
    return api

  def run_steps(self, api, engine):
    """Runs this recipe's RunSteps function.

    Args:
      * api (RecipeScriptApi) - The api object corresponding to this recipe
        (built with mk_api.)
      * engine (RecipeEngine) - The engine to use for running.

    Returns the result of RunSteps.
    """
    properties_def = self.global_symbols['PROPERTIES']
    env_properties_def = self.global_symbols.get('ENV_PROPERTIES')

    if properties_def and env_properties_def:
      if not proto_support.is_message_class(properties_def):
        raise ValueError(
            'Recipe has ENV_PROPERTIES with old-style PROPERTIES. '
            'Use a proto message for both, or use the old-style envvar '
            'support.')

    # ENV_PROPERTIES only supported in protobuf mode.
    if proto_support.is_message_class(properties_def) or env_properties_def:
      args = [api]

      if properties_def:
        # New-style Protobuf PROPERTIES.
        properties_without_reserved = {
          k: v for k, v in engine.properties.items()
          if not k.startswith('$')
        }
        args.append(jsonpb.ParseDict(
            properties_without_reserved,
            properties_def(),
            ignore_unknown_fields=True))

      if env_properties_def:
        args.append(jsonpb.ParseDict(
            {k.upper(): v for k, v in engine.environ.items()},
            env_properties_def(),
            ignore_unknown_fields=True))

      recipe_result = self.global_symbols['RunSteps'](*args)
    else:
      # Old-style Property dict.
      # NOTE: late import to avoid early protobuf import
      from .property_invoker import invoke_with_properties
      recipe_result = invoke_with_properties(
          self.global_symbols['RunSteps'], engine.properties, engine.environ,
          properties_def, api=api)
    return recipe_result


def _scan_recipe_directory(path):
  """Internal helper to yield recipe names for all recipe files under a path."""
  for root, dirs, files in os.walk(path):
    dirs[:] = [x for x in dirs
               if not x.endswith(('.expected', '.resources'))]
    for file_name in files:
      if not file_name.endswith('.py'):
        continue
      file_path = os.path.join(root, file_name)
      # raw_recipe_name has native path separators (e.g. '\\' on windows)
      raw_recipe_name = file_path[len(path)+1:-len('.py')]
      yield raw_recipe_name.replace(os.path.sep, '/')


def parse_deps_spec(repo_name, deps_spec):
  """Parses a DEPS mapping from inside a recipe or recipe module's __init__.py,
  and returns a deps map in the form of:

      {localname: (repo_name, module_name)}

  Note that this is a purely lexical transformation; no dependencies are looked
  up or verified to exist.

  Accepts:

     DEPS = ['module', 'repo/other_module']
     DEPS = {'local_name': 'module', 'other_name': 'repo/module'}

  Args:
    * repo_name (str) - The repo that unscoped dependencies should be
      resolved against.
    * deps_spec (list|tuple|dict) - The deps specification.

  Returns fully qualified deps dict of {localname: (repo_name, module_name)}
  """
  def _parse_dep_name(name):
    # dependencies can look like:
    #  * name            # uses current repo_name
    #  * repo_name/name  # explicit repo_name
    return tuple(name.split('/', 1)) if '/' in name else (repo_name, name)

  # Sequence delcaration
  if isinstance(deps_spec, (list, tuple)):
    deps = {}
    for dep_name in deps_spec:
      d_repo_name, d_module = _parse_dep_name(dep_name)
      if d_module in deps:
        raise ValueError(
          'You specified two dependencies with the name %r' % (d_module,))
      deps[d_module] = (d_repo_name, d_module)

  # Dict declaration
  elif isinstance(deps_spec, dict):
    deps = {
      local_name: _parse_dep_name(dep_name)
      for local_name, dep_name in deps_spec.items()
    }

  elif not deps_spec:
    return {}

  else:
    raise ValueError('Unknown DEPS type %r' % (type(deps_spec).__name__,))

  return deps


def _collect_import_warnings(root):
  """Traverses the dependency tree from root and collects all import warnings.

  Returns a set of (fully-qualified warning name, importing recipe or
  recipe module) tuple.
  """
  ret = set()
  recipe_deps = root.repo.recipe_deps
  for _, (repo_name, module_name) in root.normalized_DEPS.items():
    module = recipe_deps.repos[repo_name].modules[module_name]
    for warning in module.warnings:
      if '/' not in warning:
        warning = '/'.join((repo_name, warning))
      ret.add((warning, root))
    ret.update(module._cumulative_import_warnings)
  return ret


def _instantiate_test_api(module: RecipeModule, resolved_deps):
  """Instantiates the RecipeTestApi class from the given imported recipe module.

  Args:
    * resolved_deps ({local_name: None|instantiated recipe test api}) - The
      resolved RecipeTestApi instances which this module has in its DEPS. Deps
      whose value is None will be omitted. These deps will all be populated on
      `retval.m` (the ModuleInjectionSite).

  Returns the instantiated RecipeTestApi subclass.
  """
  inst = module.TEST_API(module)
  assert isinstance(inst, RecipeTestApi)
  inst.m.__dict__.update({
    local_name: resolved_dep
    for local_name, resolved_dep in resolved_deps.items()
    if resolved_dep is not None
  })
  setattr(inst.m, module.name, inst)
  return inst


def _instantiate_api(engine, test_data, fqname, module: RecipeModule, test_api,
                     resolved_deps):
  """Instantiates the RecipeApi subclass from the given imported recipe
  module.

  Args:
    * engine (run.RecipeEngine) - The recipe engine we're going to use to run
      the recipe.
    * test_data (TestData) - The test data for this run.
    * fqname (string) - The fully qualified 'repo_name/module_name' of the
      module we're instantiating.
    * test_api (RecipeTestApi) - The instantiated recipe test api object for
      this module.
    * resolved_deps ({local_name: None|instantiated recipe api}) - The resolved
      RecipeApi instances which this module has in its DEPS. Deps whose
      value is None will be omitted. These deps will all be populated on
      `retval.m` (the ModuleInjectionSite).

  Returns the instantiated RecipeApi subclass.
  """
  shortname = module.name
  kwargs = {
      'module': module,
      # BUG(crbug.com/1508497): test_data will need to use canonical unique names.
      'test_data': test_data.get_module_test_data(shortname)
  }

  imported_module = module.do_import()

  properties_def = module.PROPERTIES
  global_properties_def = getattr(imported_module, 'GLOBAL_PROPERTIES', None)
  env_properties_def = getattr(imported_module, 'ENV_PROPERTIES', None)

  if properties_def and (env_properties_def or global_properties_def):
    if not proto_support.is_message_class(properties_def):
      raise ValueError(
          'Recipe has ENV_PROPERTIES/GLOBAL_PROPERTIES with old-style '
          'PROPERTIES. Use a proto message for all, or use the old-style '
          'envvar support.')

  if (proto_support.is_message_class(properties_def)
      or env_properties_def
      or global_properties_def):
    # New-style Protobuf PROPERTIES.
    args = []

    # TODO(iannucci): deduplicate this with recipe invocation code.
    if properties_def:
      args.append(jsonpb.ParseDict(
          engine.properties.get('$' + fqname, {}),
          properties_def(),
          ignore_unknown_fields=True))

    if global_properties_def:
      properties_without_reserved = {
        k: v for k, v in engine.properties.items()
        if not k.startswith('$')
      }
      args.append(jsonpb.ParseDict(
          properties_without_reserved,
          global_properties_def(),
          ignore_unknown_fields=True))

    if env_properties_def:
      args.append(jsonpb.ParseDict(
          {k.upper(): v for k, v in engine.environ.items()},
          env_properties_def(),
          ignore_unknown_fields=True))

    inst = module.API(*args, **kwargs)
  else:
    # Old-style Property dict.
    # NOTE: late import to avoid early protobuf import
    from .property_invoker import invoke_with_properties
    inst = invoke_with_properties(module.API, engine.properties,
                                  engine.environ, properties_def, **kwargs)

  inst.test_api = test_api

  inst.m.__dict__.update(resolved_deps)
  # For awful legacy reasons, we must also load the moudles CONFIG_CTX in order
  # to have the side-effect of importing all of it's *_config.py files
  # implicitly, because doing so will modify the config of other modules.
  _ = module.CONFIG_CTX

  setattr(inst.m, shortname, inst)

  # Replace class-level Requirements placeholders in the recipe API with
  # their instance-level real values.
  for k, v in module.API.__dict__.items():
    if isinstance(v, UnresolvedRequirement):
      setattr(inst, k, engine.resolve_requirement(v))

  inst.initialize()
  return inst


def _resolve(recipe_deps, deps_spec, variant, engine, test_data):
  """Resolves a deps_spec to a map of {local_name: api instance}

  Args:
    * recipe_deps (RecipeDeps) - The loaded dependency repos.
    * deps_spec (list|dict) - The normalized DEPS specification as provided by
      the recipe/module.
    * variant ('API'|'TEST_API') - Which variant of the dependencies to load.
    * engine (None|run.RecipeEngine) - The recipe engine which will be used to
      drive the recipe. Must be None if variant == 'TEST_API'.
    * test_data (None|TestData) - The test data which will be used for the
      recipe run. Must be None if variant == 'TEST_API'.

  Returns {'local_name': loaded api instance}.
  """
  assert variant in ('API', 'TEST_API')
  if variant == 'TEST_API':
    assert engine is None
    assert test_data is None
  else:
    # NOTE: late import to avoid import cycle
    # NOTE: late import to avoid early protobuf import
    from .engine import RecipeEngine
    assert isinstance(engine, RecipeEngine)
    assert isinstance(test_data, BaseTestData)

  @attr.s(frozen=True)
  class cache_entry:
    api = attr.ib(validator=optional(attr_superclass(RecipeApi)))
    test_api = attr.ib(validator=attr_superclass(RecipeTestApi))

    def pick(self):
      return self.api if variant == 'API' else self.test_api

  # map of (repo_name, module_name) -> cache_entry
  instance_cache = {}

  def _inner(repo_name, module_name, loading_chain):
    key = (repo_name, module_name)
    if key in instance_cache:
      cached = instance_cache[key]
      if cached is None:
        first = loading_chain.index(key)
        raise CyclicalDependencyError(
          '%r has a cyclical dependency. Loading chain %r.' %
          ('%s/%s' % key, loading_chain[first:]))
      return cached
    instance_cache[key] = None
    loading_chain += [key]

    module = recipe_deps.repos[repo_name].modules[module_name]
    deps_spec = module.normalized_DEPS

    test_api = _instantiate_test_api(
        module, {
            local_name: _inner(d_repo_name, d_module, loading_chain).test_api
            for local_name, (d_repo_name, d_module) in deps_spec.items()
        })

    fqname = '%s/%s' % (repo_name, module_name)
    api = None
    if variant == 'API':
      api = _instantiate_api(
          engine, test_data, fqname, module, test_api, {
              local_name: _inner(d_repo_name, d_module, loading_chain).api
              for local_name, (d_repo_name, d_module) in deps_spec.items()
          })

    result = cache_entry(api, test_api)

    instance_cache[key] = result
    return result

  ret = {
    local_name: _inner(d_repo_name, d_module, []).pick()
    for local_name, (d_repo_name, d_module)
    in deps_spec.items()
  }

  # Always instantiate the path module at least once so that string functions on
  # Path objects work. This extra load doesn't actually attach the loaded path
  # module to the api return, so if recipes want to use the path module, they
  # still need to import it. If the recipe already loaded the path module
  # (somewhere, could be transitively), then this extra load is a no-op.
  # TODO(iannucci): The way paths work need to be reimplemented sanely :/
  _inner('recipe_engine', 'path', [])

  return ret
