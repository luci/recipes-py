#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Bundles a universe_view into a standalone folder.

This captures the result of doing all the network operations that recipe_engine
might do at startup.
"""

from __future__ import absolute_import
import errno
import logging
import os
import io
import re
import shutil
import stat
import subprocess
import sys
import types

LOGGER = logging.getLogger(__name__)

def prepare_destination(destination):
  LOGGER.info('prepping destination %s', destination)
  destination = os.path.abspath(destination)
  if os.path.exists(destination):
    LOGGER.fatal(
      'directory %s already exists! The directory must not exist to use it as '
      'a bundle target.', destination)
    sys.exit(1)
  os.makedirs(destination)
  return destination


def ls_files(pkg):
  # excludes json expectations
  flist = subprocess.check_output(['git', '-C', pkg.repo_root, 'ls-files',
                                   pkg.relative_recipes_dir or '.'])
  return [
    fpath for fpath in flist.splitlines()
    if not os.path.basename(os.path.dirname(fpath)).endswith('.expected')
  ]


def export_package(pkg, destination):
  from . import package

  LOGGER.info('exporting package: %s : %r',
              pkg.repo_root, pkg.relative_recipes_dir)

  bundle_dst = os.path.join(destination, pkg.name)

  madedirs = set()

  for relpath in ls_files(pkg):
    LOGGER.debug('  copying: %s', relpath)
    parent = os.path.dirname(relpath)
    if parent not in madedirs:
      try:
        os.makedirs(os.path.join(bundle_dst, parent))
      except OSError as err:
        if err.errno != errno.EEXIST:
          raise
      madedirs.add(parent)
    shutil.copyfile(
      os.path.join(pkg.repo_root, relpath),
      os.path.join(bundle_dst, relpath))

  cfg_path_dst = package.InfraRepoConfig().to_recipes_cfg(bundle_dst)
  if not os.path.exists(cfg_path_dst):
    cfg_path_src = package.InfraRepoConfig().to_recipes_cfg(pkg.repo_root)
    os.makedirs(os.path.dirname(cfg_path_dst))
    shutil.copyfile(cfg_path_src, cfg_path_dst)


TEMPLATE_SH = u"""#!/usr/bin/env bash
python ${BASH_SOURCE[0]%/*}/recipe_engine/recipes.py --no-fetch \
"""

TEMPLATE_BAT = u"""python "%~dp0\\recipe_engine\\recipes.py" --no-fetch ^
"""

def prep_recipes_py(universe, root_package, destination):
  from . import package

  LOGGER.info('prepping recipes.py for %s', root_package.name)
  recipes_script = os.path.join(destination, 'recipes')
  with io.open(recipes_script, 'w', newline='\n') as recipes_sh:
    recipes_sh.write(TEMPLATE_SH)

    pkg_path = package.InfraRepoConfig().to_recipes_cfg(
      '${BASH_SOURCE[0]%%/*}/%s' % root_package.name)
    recipes_sh.write(u' --package %s \\\n' % pkg_path)
    for pkg in universe.packages:
      recipes_sh.write(u' -O %s=${BASH_SOURCE[0]%%/*}/%s \\\n' %
                       (pkg.name, pkg.name))
    recipes_sh.write(u' "$@"\n')
  os.chmod(recipes_script, os.stat(recipes_script).st_mode | stat.S_IXUSR)

  with io.open(recipes_script+'.bat', 'w', newline='\r\n') as recipes_bat:
    recipes_bat.write(TEMPLATE_BAT)

    pkg_path = package.InfraRepoConfig().to_recipes_cfg(
      '"%%~dp0\\%s"' % root_package.name)
    recipes_bat.write(u' --package %s ^\n' % pkg_path)
    for pkg in universe.packages:
      recipes_bat.write(u' -O %s=%%~dp0/%s ^\n' % (
        pkg.name, pkg.name))
    recipes_bat.write(u' %*\n')


def main(root_package, universe, destination):
  """
  Args:
    root_package (package.Package) - The recipes script in the produced bundle
      will be tuned to run commands using this package.
    universe (loader.RecipeUniverse) - All of the recipes necessary to support
      root_package.
    destination (str) - Path to the bundle output folder. This folder should not
      exist before calling this function.
  """
  destination = prepare_destination(destination)
  for pkg in universe.packages:
    export_package(pkg, destination)
  prep_recipes_py(universe, root_package, destination)
