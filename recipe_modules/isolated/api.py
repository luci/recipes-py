# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib
import urllib

from recipe_engine import recipe_api

# Take revision from
# https://ci.chromium.org/p/infra-internal/g/infra-packagers/console
DEFAULT_CIPD_VERSION = 'git_revision:71f4d6c39179d79278ed4114d7044290ca0a25cf'


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
    self._namespace = isolated_properties.get('namespace', 'default-gzip')
    default_cipd_version = DEFAULT_CIPD_VERSION
    if self._test_data.enabled:
      default_cipd_version = 'isolated_module_pin'
    self._version = isolated_properties.get('version', default_cipd_version)

  def initialize(self):
    if self._test_data.enabled:
      self._server = 'https://example.isolateserver.appspot.com'
    if self.m.runtime.is_experimental:
      self._version = 'latest'

  @property
  def _client(self):
    """Ensures that the isolated Go binary is installed."""
    return self.m.cipd.ensure_tool('infra/tools/luci/isolated/${platform}',
                                   self._version)

  @property
  def isolate_server(self):
    """Returns the associated isolate server."""
    assert self._server
    return self._server

  @property
  def namespace(self):
    """Returns the associated namespace."""
    assert self._namespace
    return self._namespace

  def _run(self, name, cmd, step_test_data=None):
    """Return an isolated command step.
    Args:
      name: (str): name of the step.
      cmd (list(str|Path)): isolated client subcommand to run.
    """
    return self.m.step(name,
                       [self._client] + list(cmd),
                       step_test_data=step_test_data,
                       infra_step=True)

  @contextlib.contextmanager
  def on_path(self):
    """This context manager ensures the go isolated client is available on
    $PATH.

    Example:

        with api.isolated.on_path():
          # do your steps which require the isolated binary on path
    """
    client_dir = self.m.path.dirname(self._client)
    with self.m.context(env_prefixes={'PATH': [client_dir]}):
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
      isolate_server (str|None): an isolate server to download from; if None,
        the module's default server will be used instead.
    """
    isolate_server = isolate_server or self.isolate_server
    cmd = [
        'download',
        '-verbose',
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
        '-verbose',
        '-isolate-server', isolate_server,
        '-namespace', self._api.isolated.namespace,
        '-dump-hash', self._api.raw_io.output_text(),
    ]
    for f in self._files:
      cmd.extend(['-files', self._isolated_path_format(f)])
    for d in self._dirs:
      cmd.extend(['-dirs', self._isolated_path_format(d)])
    isolated_hash = self._api.isolated._run(
        step_name,
        cmd,
        step_test_data=self._api.isolated.test_api.archive,
    ).raw_io.output_text
    q = {
      'hash': isolated_hash,
      'namespace': self._api.isolated.namespace,
    }
    self._api.step.active_result.presentation.links['isolated UI'] = (
      '%s/browse?%s' % (isolate_server, urllib.urlencode(q))
    )
    return isolated_hash
