# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib

from recipe_engine import recipe_api


DEFAULT_CIPD_VERSION = 'git_revision:5c78afc7db0efe3c70843bee7c3fd991ef29326c'


class IsolatedApi(recipe_api.RecipeApi):
  """API for interacting with isolated.

  The isolated client implements a tar-like scatter-gather mechanism for
  archiving files. The tool's source lives at
  http://go.chromium.org/luci/client/cmd/isolated.

  This module will deploy the client to [CACHE]/isolated_client/; users should
  add this path to the named cache for their builder.
  """

  def __init__(self, isolated_properties, *args, **kwargs):
    super(IsolatedApi, self).__init__(*args, **kwargs)
    self._server = isolated_properties.get('server', None)
    self._version = isolated_properties.get('version', DEFAULT_CIPD_VERSION)
    self._client_dir = None
    self._client = None

  def initialize(self):
    if self._test_data.enabled:
      self._server = 'https://example.isolateserver.appspot.com'
    if self.m.runtime.is_experimental:
      self._version = 'latest'
    self._client_dir = self.m.path['cache'].join('isolated_client')

  def _ensure_isolated(self):
    """Ensures that the isolated Go binary is installed."""
    if self._client:
      return

    with self.m.step.nest('ensure isolated'):
      with self.m.context(infra_steps=True):
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('infra/tools/luci/isolated/${platform}', self._version)
        self.m.cipd.ensure(self._client_dir, pkgs)
        self._client = self._client_dir.join('isolated')

  @property
  def isolate_server(self):
    """Returns the associated isolate server."""
    assert self._server
    return self._server

  def _run(self, name, cmd, step_test_data=None):
    """Return an isolated command step.
    Args:
      name: (str): name of the step.
      cmd (list(str|Path)): isolated client subcommand to run.
    """
    self._ensure_isolated()
    return self.m.step(name,
                       [self._client] + list(cmd),
                       step_test_data=step_test_data)

  @contextlib.contextmanager
  def on_path(self):
    """This context manager ensures the go isolated client is available on
    $PATH.

    Example:

        with api.isolated.on_path():
          # do your steps which require the isolated binary on path
    """
    self._ensure_isolated()
    with self.m.context(env_prefixes={'PATH': [self._client_dir]}):
      yield

  def isolated(self, root_dir):
    """Returns an Isolated object that can be used to archive a set of files
    and directories, relative to a given root directory.

    Args:
      root_dir (Path): directory relative to which files and directory will be
        isolated.
    """
    return Isolated(self.m, root_dir)

  def download(self, step_name, isolated_hash, output_dir, isolate_server=None):
    """Downloads an isolated tree from an isolate server.

    Args:
      step_name (str): name of the step.
      isolated_hash (str): the hash of an isolated tree.
      output_dir (Path): Path to an output directory. If a non-existent
        directory, it will be created; else if already existent,
        conflicting files will be overwritten and non-conflicting files
        already in the directory will be ignored.
      isolate_server (str|None): an isolate server to donwload from; if None,
        the module's default server will be used instead.
    """
    isolate_server = isolate_server or self.isolate_server
    cmd = [
        'download',
        '-isolate-server', isolate_server,
        '-isolated', isolated_hash,
        '-output-dir', output_dir,
    ]
    return self._run(step_name, cmd)


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
    if self._root_dir.is_parent_of(path):
      return '%s:%s' % (
          self._root_dir,
          self._api.path.join(*path.pieces[len(self._root_dir.pieces):])
      )
    else:
      assert path == self._root_dir, \
        "isolated path must be equal to or within %s" % self._root_dir
      return '%s:.' % self._root_dir

  def add_file(self, path):
    """Stages a single file to be added to the isolated.

    Args:
      path (Path): absolute path to a file.
    """
    assert self._root_dir.is_parent_of(path)
    self._files.append(path)

  def add_files(self, paths):
    """Stages a list of files to be added to the isolated.

    Args:
      paths list(Path): list of absolute paths to files.
    """
    for path in paths:
      self.add_file(path)

  def add_dir(self, path):
    """Stages a single directory to be added to the isolated.

    Args:
      path (Path): absolute path to a directory.
    """
    assert self._root_dir == path or self._root_dir.is_parent_of(path)
    self._dirs.append(path)

  def archive(self, step_name, isolate_server=None):
    """Step to archive all staged files and directories.

    If no isolate_server is provided, the IsolatedApis's default server will be
    used instead.

    Args:
      step_name (str): name of the step.
      isolate_server (str): an isolate server to archive to.

    Returns:
      The hash of the isolated tree.
    """
    isolate_server = isolate_server or self._api.isolated.isolate_server
    cmd = [
        'archive',
        '-isolate-server', isolate_server,
        '-namespace', 'default-gzip',
        '-dump-hash', self._api.raw_io.output_text(),
    ]
    for f in self._files:
      cmd.extend(['-files', self._isolated_path_format(f)])
    for d in self._dirs:
      cmd.extend(['-dirs', self._isolated_path_format(d)])
    return self._api.isolated._run(
        step_name,
        cmd,
        step_test_data=self._api.isolated.test_api.archive,
    ).raw_io.output_text
