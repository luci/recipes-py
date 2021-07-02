# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This package houses all subcommands for the recipe engine.

See implementation_details.md for the expectations of the modules in this
directory.
"""

from builtins import zip
from future.utils import iteritems
import argparse
import errno
import logging
import os
import pkgutil
import sys

if sys.version_info >= (3, 5): # we're running python > 3.5
  OS_WALK = os.walk
else:
  # From vpython
  from scandir import walk as OS_WALK

# pylint: disable=wrong-import-position
from .. import simple_cfg
from ..recipe_deps import RecipeDeps
from ..recipe_module_importer import RecipeModuleImporter


LOG = logging.getLogger(__name__)

# This incantation finds all loadable submodules of ourself. The
# `prefix=__name__` bit is so that these modules get loaded with the correct
# import names, i.e.
#
#    recipe_engine.internal.commands.<submodule>
#
# If omitted, then these submodules can get double loaded as both:
#
#    <submodule> AND
#    recipe_engine.internal.commands.<submodule>
#
# Which can both interfere with the global python module namespace, and lead to
# strange errors when doing type assertions (since all data in these modules
# will be loaded under two different names; classes will fail isinstance checks
# even though they are "the same").
_COMMANDS = [
  loader.find_module(module_name).load_module(module_name)
  for (loader, module_name, _) in pkgutil.walk_packages(
      __path__, prefix=__name__+'.')
  if '.' not in module_name[len(__name__)+1:]
]

# Order all commands by an optional __cmd_priority__ field, and then by module
# name.
_COMMANDS.sort(
    key=lambda mod: (
      not hasattr(mod, '__cmd_priority__'),   # modules defining priority first
      getattr(mod, '__cmd_priority__', None), # actual priority
      mod.__name__                            # name
    ))

# Now actually set these commands on ourself so that 'mock' works correctly.
#
# This is needed to allow some tests (though it may be worth adjusting these
# tests later to not need this. Just delete this function and see which tests
# fail to find the dependencies on this behavior).
def _patch_our_attrs():
  self = sys.modules[__name__]
  self.__all__ = [mod.__name__[len(__name__)+1:] for mod in _COMMANDS]
  for modname, mod in zip(self.__all__, _COMMANDS):
    setattr(self, modname, mod)
_patch_our_attrs()


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
    for req_repo_name, req_spec in iteritems(required_deps):
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
  for repo in recipe_deps.repos.values():
    for to_walk in (repo.recipes_dir, repo.modules_dir):
      for root, _dirs, files in OS_WALK(to_walk):
        for fname in files:
          if not fname.endswith('.pyc'):
            continue

          try:
            to_clean = os.path.join(root, fname)
            LOG.info('cleaning %r', to_clean)
            os.unlink(to_clean)
          except OSError as ex:
            # If multiple things are cleaning pyc's at the same time this can
            # race. Fortunately we only care that SOMETHING deleted the pyc :)
            if ex.errno != errno.ENOENT:
              raise


def _common_post_process(args):
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

  if args.pid_file:
    try:
      with open(args.pid_file, 'w') as pid_file:
        pid_file.write('%d\n' % os.getpid())
    except Exception:
      logging.exception("unable to write pidfile")

  args.recipe_deps = RecipeDeps.create(
      args.main_repo_path,
      args.repo_override,
      args.proto_override,
  )

  _check_recipes_cfg_consistency(args.recipe_deps)

  # Allows:
  #   import RECIPE_MODULES.repo_name.module_name.submodule
  sys.meta_path = [RecipeModuleImporter(args.recipe_deps)] + sys.meta_path

  _cleanup_pyc(args.recipe_deps)

  # Remove flags that subcommands shouldn't use; everything from this point on
  # should ONLY use args.recipe_deps.
  del args.main_repo_path
  del args.verbose
  del args.repo_override


def _add_common_args(parser):
  class _RepoOverrideAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      tokens = values.split('=', 2)
      if len(tokens) != 2:
        raise ValueError('Override must have the form: repo=path')
      repo_name, path = tokens

      override_dict = getattr(namespace, self.dest)

      if repo_name in override_dict:
        raise ValueError('An override is already defined for [%s] (%s)' % (
                         repo_name, override_dict[repo_name]))
      path = os.path.abspath(os.path.expanduser(path))
      if not os.path.isdir(path):
        raise ValueError('Override path [%s] is not a directory' % (path,))
      override_dict[repo_name] = path

  def _package_to_main_repo(value):
    try:
      value = os.path.abspath(value)
    except Exception as ex:  # pylint: disable=broad-except
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
      dest='main_repo_path', type=_package_to_main_repo, required=True,
      help='Path to recipes.cfg of the recipe repo to operate on.')
  parser.add_argument(
      '--verbose', '-v', action='count', default=0,
      help='Increase logging verboisty')
  parser.add_argument('-O', '--repo-override', metavar='ID=PATH',
      action=_RepoOverrideAction, default={},
      help='Override a repo repository path with a local one.')
  parser.add_argument('--pid-file', metavar='PATH',
      help=(
        'Absolute path to a file where the engine should write its pid. '
        'Path must be absolute and not exist.'))

  def _proto_override_abspath(value):
    try:
      value = os.path.abspath(value)
    except Exception as ex:  # pylint: disable=broad-except
      parser.error(
          '--proto-override %r could not be converted to absolute path: %r' % (
            value, ex,))

    return value

  # Override the location of the folder containing the `PB` module. This should
  # only be used for recipe bundles, so we don't bother giving it a shortform
  # option, and suppress the option's help to avoid confusing users.
  parser.add_argument(
      '--proto-override', type=_proto_override_abspath, help=argparse.SUPPRESS)

  parser.set_defaults(
    postprocess_func=lambda error, args: None,
  )


def parse_and_run():
  """Parses the command line and runs the chosen subcommand.

  Returns the command's return value (either int or None, suitable as input to
  `os._exit`).
  """
  parser = argparse.ArgumentParser(
      description='Interact with the recipe system.')

  _add_common_args(parser)

  subp = parser.add_subparsers(dest='command')
  for module in _COMMANDS:
    description = module.__doc__
    helplines = []
    for line in description.splitlines():
      line = line.strip()
      if not line:
        break
      helplines.append(line)
    module.add_arguments(subp.add_parser(
        module.__name__.split('.')[-1],  # use module's short name
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help=' '.join(helplines),
        description=description,
    ))

  args = parser.parse_args()
  _common_post_process(args)
  args.postprocess_func(parser.error, args)

  try:
    return args.func(args)
  finally:
    # Any file-like objects directly attached to args need to be closed
    # explicitly here because otherwise main.py will do an os._exit and any
    # buffered data in these files could be lost.
    for value in vars(args).values():
      if hasattr(value, 'close'):
        value.close()
