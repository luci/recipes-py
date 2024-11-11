# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import logging
import os
import sys

from gevent import subprocess

from ...recipe_deps import RecipeDeps

LOGGER = logging.getLogger(__name__)
CIPD = 'cipd.bat' if sys.platform == 'win32' else 'cipd'
BUNDLE_RECIPE_PKG_NAME = 'infra/tools/luci/bundle_recipe'
BUNDLE_RECIPE_VERSION = '	git_revision:e995ce992ce5c615c6a25f63b7e33b6467ee92c3'


def _bundle_recipe(recipe_deps: RecipeDeps, dest: str) -> None:
  """Downloads bundle_recipe package and invoke it to bundle this recipe repo.

  Args:
    * recipe_deps (RecipeDeps) - All loaded dependency repos.
    * dest (str) - destination path to bundle recipe to.
  """
  LOGGER.info(f'installing {BUNDLE_RECIPE_PKG_NAME}')
  install_root = os.path.join(recipe_deps.recipe_deps_path, 'cipd_pkgs',
                              'bundle_recipe')
  cipd_proc = subprocess.Popen(
    [CIPD, 'ensure', '-root', install_root, '-ensure-file', '-'],
    stdin=subprocess.PIPE, text=True)
  cipd_proc.communicate(
    f'{BUNDLE_RECIPE_PKG_NAME}/${{platform}} {BUNDLE_RECIPE_VERSION}')
  if cipd_proc.returncode != 0:
    raise ValueError(
        f'failed to install bundle_recipe: retcode: {cipd_proc.returncode}')

  bundle_cmd = [
      os.path.join(install_root, 'bundle_recipe'),
      '-repo-root', recipe_deps.main_repo.path,
      '-dest', dest]
  LOGGER.debug('running %s' % bundle_cmd)
  subprocess.run(bundle_cmd,check=True)
  LOGGER.info('done!')


def main(args):
  _bundle_recipe(args.recipe_deps, args.destination)
