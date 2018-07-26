# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Bundles a universe_view into a standalone folder.

This captures the result of doing all the network operations that recipe_engine
might do at startup to fetch repo code.

This is a bit hacky, however, the API is solid. The general principle is that
the input to bundle is:
  * a universe
  * a package manifest
  * files tagged with the `recipes` gitattribute value (see
    `git help gitattributes`).
And the output is:
  * a runnable folder for the named package

Some things that we'd want to do to make this better:
  * Allow this to fetch lazily from gitiles (no git clones)
    * will be necessary to support HUGE repos like chromium/src
  * Allow this to target a specific subset of runnable recipes (maybe)
    * prune down to ONLY the modules which are required to run those particular
      recipes.
    * this may be more trouble than it's worth

Included files

By default, bundle will include all recipes/ and recipe_modules/ files in your
repo, plus the `recipes.cfg` file, and excluding all json expectation files.

Recipe bundle also uses the standard `gitattributes` mechanism for tagging files
within the repo, and will also include these files when generating the bundle.
In particular, it looks for files tagged with the string `recipes`. As an
example, you could put this in a `.gitattributes` file in your repo:

```
*.py       recipes
*_test.py -recipes
```

That would include all .py files, but exclude all _test.py files. See the page
  `git help gitattributes`
For more information on how gitattributes work.
"""

from __future__ import absolute_import
import errno
import io
import logging
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys

from collections import defaultdict

from . import loader
from . import package
from . import package_io

LOGGER = logging.getLogger(__name__)
GIT = 'git.bat' if sys.platform == 'win32' else 'git'

def check(obj, typ):
  if not isinstance(obj, typ):
    msg = '%r was %s, expected %s' % (obj, type(obj).__name__, typ.__name__)
    LOGGER.debug(msg)
    raise TypeError(msg)


def prepare_destination(destination):
  check(destination, str)

  destination = os.path.abspath(destination)
  LOGGER.info('prepping destination %s', destination)
  if os.path.exists(destination):
    if os.listdir(destination):
      LOGGER.fatal(
        'directory %s exists and is non-empty! The directory must be empty or'
        ' missing to use it as a bundle target.', destination)
      sys.exit(1)
  else:
    os.makedirs(destination)
  return destination


def export_package(pkg, destination):
  check(pkg, package.Package)
  check(destination, str)

  bundle_dst = os.path.join(destination, pkg.name)

  reldir = pkg.relative_recipes_dir
  if reldir:
    reldir += '/'

  args = [
    GIT, '-C', pkg.repo_root, 'ls-files', '--',
    ':(attr:recipes)',                  # anything tagged for recipes
    package_io.InfraRepoConfig.RELPATH, # always grab the recipes.cfg file
    '%srecipes/**' % reldir,            # all the recipes stuff
    '%srecipe_modules/**' % reldir,     # all the recipe_modules stuff

    # And exclude all the json expectations
    ':(exclude)%s**/*.expected/*.json' % reldir,
  ]
  LOGGER.info('enumerating all recipe files: %r' % (args,))
  to_copy = subprocess.check_output(args).splitlines()
  copy_map = defaultdict(set)
  for i in to_copy:
    if posixpath.sep != os.path.sep:
      i = i.replace(posixpath.sep, os.path.sep)
    while i:
      i, tail = os.path.split(i)
      base = os.path.join(pkg.repo_root, i) if i else pkg.repo_root
      copy_map[base].add(tail)

  def ignore_fn(base, items):
    return set(items) - copy_map[base]

  shutil.copytree(pkg.repo_root, bundle_dst, ignore=ignore_fn)


TEMPLATE_SH = u"""#!/usr/bin/env bash
vpython -u ${BASH_SOURCE[0]%/*}/recipe_engine/recipes.py \
"""

TEMPLATE_BAT = u"""call vpython.bat -u "%~dp0\\recipe_engine\\recipes.py" ^
"""

def prep_recipes_py(universe, root_package, destination):
  check(universe, loader.RecipeUniverse)
  check(root_package, package.Package)
  check(destination, str)

  overrides = [pkg.name for pkg in universe.packages
               if pkg.name != universe.package_deps.root_package.name]

  LOGGER.info('prepping recipes.py for %s', root_package.name)
  recipes_script = os.path.join(destination, 'recipes')
  with io.open(recipes_script, 'w', newline='\n') as recipes_sh:
    recipes_sh.write(TEMPLATE_SH)

    pkg_path = package_io.InfraRepoConfig().to_recipes_cfg(
      '${BASH_SOURCE[0]%%/*}/%s' % root_package.name)
    recipes_sh.write(u' --package %s \\\n' % pkg_path)
    for o in overrides:
      recipes_sh.write(u' -O %s=${BASH_SOURCE[0]%%/*}/%s \\\n' % (o, o))
    recipes_sh.write(u' "$@"\n')
  os.chmod(recipes_script, os.stat(recipes_script).st_mode | stat.S_IXUSR)

  with io.open(recipes_script+'.bat', 'w', newline='\r\n') as recipes_bat:
    recipes_bat.write(TEMPLATE_BAT)

    pkg_path = package_io.InfraRepoConfig().to_recipes_cfg(
      '"%%~dp0\\%s"' % root_package.name)
    recipes_bat.write(u' --package %s ^\n' % pkg_path)
    for o in overrides:
      recipes_bat.write(u' -O %s=%%~dp0/%s ^\n' % (o, o))
    recipes_bat.write(u' %*\n')


def add_subparser(parser):
  bundle_p = parser.add_parser(
    'bundle',
    help='Create a hermetically runnable recipe bundle.',
    description=(
      'Create a hermetically runnable recipe bundle. This captures the result'
      ' of all network operations the recipe_engine might normally do to'
      ' bootstrap itself. This requires a git version >= 2.13+.'))
  bundle_p.add_argument(
    '--destination', default='./bundle',
    type=os.path.abspath,
    help='The directory of where to put the bundle (default: %(default)r).')

  def postprocess_func(parser, _args):
    raw = subprocess.check_output([GIT, 'version'])
    m = re.match('git version (\d+\.\d+\.\d+).*', raw)
    if not m:
      parser.error('could not parse git version from %r' % raw)
    vers = tuple(map(int, m.group(1).split('.')))
    if vers < (2, 13, 0):
      parser.error('git version %r is too old (need 2.13+)' % raw)

  bundle_p.set_defaults(func=main, postprocess_func=postprocess_func)


def main(package_deps, args):
  """
  Args:
    root_package (package.Package) - The recipes script in the produced bundle
      will be tuned to run commands using this package.
    universe (loader.RecipeUniverse) - All of the recipes necessary to support
      root_package.
    destination (str) - Path to the bundle output folder. This folder should not
      exist before calling this function.
  """
  universe = loader.RecipeUniverse(package_deps, args.package)
  destination = args.destination
  root_package = package_deps.root_package

  logging.basicConfig()
  destination = prepare_destination(args.destination)
  for pkg in universe.packages:
    export_package(pkg, destination)
  prep_recipes_py(universe, root_package, destination)
  LOGGER.info('done!')
