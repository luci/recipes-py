# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Contains all logic w.r.t. the recipe engine's support for development
environments.

This includes generation of .recipe_deps/_dev folder, which includes:
  * python3 -> a symlink to the current virtualenv interpreter
  * typings -> a root folder for type stubs
"""

from __future__ import annotations

import logging
import sys
import importlib.util

from pathlib import Path

from . import recipe_deps

def _tryEnsureSymlink(p: Path, to: str|Path):
  """Ensures that `p` is a symlink which points to `to`.

  `to` must be a directory.

  No-op if `p` already exists and points to `to`.

  Logs warning if link could not be created, but does not fail - Windows
  systems not configured to allow symlinks may see these warnings.

  This is not an atomic operation - it could unlink the existing file and then
  fail to create the symlink, leaving `p` in a removed state.
  """
  curVal = None
  try:
    curVal = p.readlink()
  except:
    pass

  if curVal != to:
    try:
      p.unlink(missing_ok=True)
      p.symlink_to(to)
    except OSError as ex:
      logging.warning("unable to create link %r: %s", p, ex)


def ensure_venv(deps: recipe_deps.RecipeDeps):
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

  _tryEnsureSymlink(venvDir/name, sys.prefix)


def ensure_pathdir(deps: recipe_deps.RecipeDeps):
  """Ensures that the .recipe_deps/_path directory exists.

  This directory will contain RECIPE_MODULES, PB, recipe_engine, and can be
  added to pythonpath for tools like pylint.
  """
  pathDir = Path(deps.recipe_deps_path)/"_path"
  pathDir.mkdir(parents=True, exist_ok=True)

  _tryEnsureSymlink(pathDir/'PB', Path(deps.protos_path)/'PB')
  _tryEnsureSymlink(pathDir/'recipe_engine',
                 Path(deps.repos['recipe_engine'].path)/'recipe_engine')

  modsDir = Path(pathDir/'RECIPE_MODULES')
  modsDir.mkdir(parents=True, exist_ok=True)

  for reponame, repo in deps.repos.items():
    _tryEnsureSymlink(modsDir/reponame, repo.modules_dir)
