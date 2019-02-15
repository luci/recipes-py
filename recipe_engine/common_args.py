# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Command line parsing common arguments.

This generates the 'top level' ArgumentParser object; all subcommands then
augment it with their own subcommands and flags.

This is responsible for first-pass post-processing of the arguments, including:
  * Checking recipes.cfg consistency across all repos.
  * Making all repo dependencies up-to-date.
  * Instantiating the RecipeDeps object used by all subcommands.
"""

# TODO(iannucci) - move to internal module.

import argparse
import errno
import logging
import os
import sys

if sys.version_info >= (3, 5): # we're running python > 3.5
  OS_WALK = os.walk
else:
  # From vpython
  from scandir import walk as OS_WALK

from .internal import simple_cfg
from .internal.recipe_deps import RecipeDeps
from .internal.recipe_module_importer import RecipeModuleImporter


LOG = logging.getLogger(__name__)


def _check_recipes_cfg_consistency(recipe_deps):
  """Checks all recipe.cfg files for the loaded recipe_deps and logs
  inconsistent dependencies.

  Args:
    recipe_deps (RecipeDeps) - The loaded+fetched recipe deps
      for the current run.
  """
  actual = recipe_deps.main_repo.simple_cfg.deps
  # For every repo we loaded
  for repo_name in actual:
    required_deps = recipe_deps.repos[repo_name].simple_cfg.deps
    for req_repo_name, req_spec in required_deps.iteritems():
      # If this depends on something we didn't load, log an error.
      if req_repo_name not in actual:
        LOG.error(
          '%r depends on %r, but your recipes.cfg is missing an '
          'entry for this.', repo_name, req_repo_name)
        continue

      actual_spec = actual[req_repo_name]
      if req_spec.revision == actual_spec.revision:
        # They match, it's all good.
        continue

      LOG.warn(
        'recipes.cfg depends on %r @ %s, but %r depends on version %s.',
        req_repo_name, actual_spec.revision, repo_name, req_spec.revision)


def _cleanup_pyc(recipe_deps):
  """Removes any .pyc files from the recipes/recipe_module directories.

  Args:
    * recipe_deps (RecipeDeps) - The loaded recipe dependencies.
  """
  for repo in recipe_deps.repos.itervalues():
    for relpath in ('recipes', 'recipe_modules'):
      to_walk = os.path.join(repo.recipes_root_path, relpath)
      for root, _dirs, files in OS_WALK(to_walk):
        for f in files:
          if f.endswith('.pyc'):
            try:
              to_clean = os.path.join(root, f)
              LOG.info('cleaning %r', to_clean)
              os.unlink(to_clean)
            except OSError as ex:
              # If multiple things are cleaning pyc's at the same time this can
              # race. Fortunately we only care that SOMETHING deleted the pyc :)
              if ex.errno != errno.ENOENT:
                raise


def add_common_args(parser):
  """This adds 'common' arguments to the given ArgumentParser.

  This consists of:
    * `-O`: repo overrides
    * `--package`: Path to the recipes.cfg file
    * `--verbose`: Path to the recipes.cfg file

  Returns a function post_process_args(args) which must be called on the `args`
  returned by parser.parse().
  """

  class RepoOverrideAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      p = values.split('=', 2)
      if len(p) != 2:
        raise ValueError('Override must have the form: repo=path')
      repo_name, path = p

      v = getattr(namespace, self.dest)

      if repo_name in v:
        raise ValueError('An override is already defined for [%s] (%s)' % (
                         repo_name, v[repo_name]))
      path = os.path.abspath(os.path.expanduser(path))
      if not os.path.isdir(path):
        raise ValueError('Override path [%s] is not a directory' % (path,))
      v[repo_name] = path

  def package_to_main_repo(value):
    try:
      value = os.path.abspath(value)
    except Exception as ex:
      parser.error(
          '--package %r could not be converted to absolute path: %r' % (
            value, ex,))

    recipes_cfg_rel = simple_cfg.RECIPES_CFG_LOCATION_REL
    if not value.endswith(recipes_cfg_rel):
      parser.error('--package must end with %r.' % (recipes_cfg_rel,))

    # We know the arg ends with 'infra/config/recipes.cfg', so chop those
    # elements off the path to get the path to the recipe repo root.
    for _ in simple_cfg.RECIPES_CFG_LOCATION_TOKS:
      value = os.path.dirname(value)

    return value


  # TODO(iannucci): change --package to --repo-path and avoid having recipes.py
  # pass the path to the recipes.cfg. This is preferable because the location of
  # recipes.cfg MUST be discovered for recipe dependencies; the RepoSpec
  # protobuf doesn't specify where the recipes.cfg is in the dependency repos
  # (nor can it, even if it was dynamic; this would be a nightmare to maintain,
  # and the autoroller would need to discover it automatically ANYWAY. If we
  # allow it to be relocatable, the engine needs to be able to discover it, in
  # which case the minimal information is still 'repo root').
  parser.add_argument(
      '--package',
      dest='main_repo_path', type=package_to_main_repo, required=True,
      help='Path to recipes.cfg of the recipe repo to operate on.')
  parser.add_argument(
      '--verbose', '-v', action='count',
      help='Increase logging verboisty')
  parser.add_argument('-O', '--repo-override', metavar='ID=PATH',
      action=RepoOverrideAction, default={},
      help='Override a repo repository path with a local one.')

  parser.set_defaults(
    postprocess_func=lambda parser, args: None,
  )

  def post_process_args(args):
    # TODO(iannucci): We should always do logging.basicConfig() (probably with
    # logging.WARNING), even if no verbose is passed. However we need to be
    # careful as this could cause issues with spurious/unexpected output.
    # Once the recipe engine is on native build.proto, this should be safe to
    # do.
    if args.verbose > 0:
      logging.basicConfig()
      logging.getLogger().setLevel(logging.INFO)
      if args.verbose > 1:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
      # Prevent spurious "No handlers could be found for ..." stderr messages.
      # Once we always set a basicConfig (per TODO above), this can go away as
      # well.
      logging.root.manager.emittedNoHandlerWarning = True

    args.recipe_deps = RecipeDeps.create(
      args.main_repo_path,
      args.repo_override,
    )

    _check_recipes_cfg_consistency(args.recipe_deps)

    # Allows:
    #   import RECIPE_MODULES.repo_name.module_name.submodule
    sys.meta_path = [RecipeModuleImporter(args.recipe_deps)] + sys.meta_path

    _cleanup_pyc(args.recipe_deps)

  return post_process_args
