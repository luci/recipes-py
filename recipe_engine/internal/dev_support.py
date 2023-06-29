# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Contains all logic w.r.t. the recipe engine's support for development
environments.

This includes generation of .recipe_deps/_dev folder, which includes:
  * python3 -> a symlink to the current virtualenv interpreter
  * typings -> a root folder for type stubs
"""

import logging
import sys
import tempfile
import importlib.util

from pathlib import Path

from . import recipe_deps


def ensure_venv(deps: 'recipe_deps.RecipeDeps'):
  """Ensures that the .recipe_deps/_venvs/$env symlink is generated.

  $env is calculated as:
    * vscode  - .vscode.vpython3
    * pycharm - .pycharm.vpython3
    * normal  - .vpython3

  No-op on windows.
  """
  name = 'normal'
  if importlib.util.find_spec('debugpy'):
    name = 'vscode'
  elif importlib.util.find_spec('pydevd'):
    name = 'pycharm'

  venvDir = Path(deps.recipe_deps_path)/"_venv"
  venvDir.mkdir(parents=True, exist_ok=True)

  curLink = venvDir/name

  curLinkVal = None
  try:
    curLinkVal = curLink.readlink()
  except:
    pass

  if curLinkVal != sys.prefix:
    tmpLink = Path(tempfile.mktemp(prefix='venv_', dir=venvDir))
    try:
      tmpLink.symlink_to(sys.prefix, target_is_directory=True)
      tmpLink.replace(curLink)
    except OSError as ex:
      logging.warn("unable to create virtualenv link %r: %s", curLink, ex)
    finally:
      try:
        tmpLink.unlink(missing_ok=True)
      except:
        pass
