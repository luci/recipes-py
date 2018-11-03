# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import os


class IsolatedApi(recipe_api.RecipeApi):
  """API for interacting with isolated.

  The isolated client implements a tar-like scatter-gather mechanism for
  archiving files. The tool's source lives at
  http://go.chromium.org/luci/client/cmd/isolated.
  """

  def __init__(self, isolated_properties, *args, **kwargs):
    super(IsolatedApi, self).__init__(*args, **kwargs)
    self._default_isolate_server = isolated_properties.get('default_isolate_server')
    self._isolated_version = isolated_properties.get('isolated_version', 'release')
    self._isolated_client = None

  def _ensure_isolated(self):
    """Ensures that the isolated Go binary is installed."""
    if self._isolated_client:
      return

    with self.m.step.nest('ensure_isolated'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('infra/tools/luci/isolated/${platform}',
                         self._isolated_version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._isolated_client = cipd_dir.join('isolated', 'isolated')

  def run(self, name, cmd, step_test_data=None):
    """Return an isolated command step.
    Args:
      name: (str): name of the step.
      cmd (list(str|Path)): isolated client subcommand to run.
    """
    self._ensure_isolated()
    return self.m.step(name,
                       [self._isolated_client] + list(cmd),
                       step_test_data=step_test_data)

  def isolated(self, root_dir):
    """Returns an Isolated object that can be used to archive a set of files
    and directories, relative to a given root directory.

    Args:
      root_dir (Path): directory relative to which files and directory will be
        isolated.
    """
    return Isolated(self, root_dir)


class Isolated(object):
  """Used to gather a list of files and directories to an isolated, relative to
  a provided root directory."""

  def __init__(self, api, root_dir):
    assert root_dir
    self._api = api
    self._root_dir = root_dir
    self._files = []
    self._dirs = []

  def _isolated_path_format(self, path):
    """Returns the path format consumed by the isolated CLI."""
    return str(self._root_dir) + ':' + os.path.relpath(str(path), str(self._root_dir))

  def add_file(self, path):
    """Stages a single file to be added to the isolated.

    Args:
      path (Path): absolute path to a file.
    """
    assert path
    self._files.append(path)

  def add_dir(self, path):
    """Stages a single directory to be added to the isolated.

    Args:
      path (Path): absolute path to a directory.
    """
    assert path
    self._dirs.append(path)

  def archive(self, step_name, isolate_server=None):
    """Step to archive all staged files and directories.

    If no isolate_server is provided, the IsolatedApis's default server will be
    used instead.

    Args:
      step_name (str): name of the step.
      isolate_server (str): an isolate server to archive to.

    Returns:
      The hash of the isolated file.
    """
    isolate_server = isolate_server or self._api._default_isolate_server
    cmd = [
        'archive',
        '-isolate-server', isolate_server,
        '-namespace', 'default-gzip',
        '-dump-hash', self._api.m.raw_io.output_text(),
    ]
    for f in self._files:
      cmd.extend(['-files', self._isolated_path_format(f)])
    for d in self._dirs:
      cmd.extend(['-dirs', self._isolated_path_format(d)])
    return self._api.run(
        step_name,
        cmd,
        step_test_data=lambda: self._api.test_api.archive(),
    ).raw_io.output_text
