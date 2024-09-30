# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with cas client."""

import contextlib

from recipe_engine import recipe_api


class CasApi(recipe_api.RecipeApi):
  """A module for interacting with cas client."""

  def __init__(self, env_properties, **kwargs):
    super().__init__(**kwargs)

    self._instance = None
    self._cached_version = None
    self._env_properties = env_properties

  @property
  def instance(self):
    if self._instance:
      return self._instance

    swarming_server = (
      self._env_properties.SWARMING_SERVER or
      'https://example-cas-server.appspot.com')
    project = swarming_server[len('https://'):-len('.appspot.com')]

    # Set full instance name if only project ID is given.
    self._instance = 'projects/%s/instances/default_instance' % project

    return self._instance

  @contextlib.contextmanager
  def with_instance(self, instance):
    """Sets the CAS instance while in context, then reverts it."""
    previous_instance = self._instance
    try:
      self._instance = instance
      yield
    finally:
      self._instance = previous_instance

  @property
  def _version(self):
    if self.m.runtime.is_experimental:
      return 'latest'

    if self._cached_version is None:
      self._cached_version = self.m.file.read_text(
          "read infra revision",
          # This has revision of https://chromium.googlesource.com/infra/infra/.
          self.resource("infra.sha1"),
          test_data='git_revision:mock_infra_git_revision').strip()

    return self._cached_version

  def _run(self, name, cmd, step_test_data=None, **kwargs):
    """Returns a cas command step.

    Args:
      * name: (str): name of the step.
      * cmd (list(str|Path)): cas client subcommand to run.
      * kwargs: Additional keyword arguments to forward to "step".
    """
    kwargs.setdefault('infra_step', True)
    return self.m.step(
        name,
        [
            self.m.cipd.ensure_tool('infra/tools/luci/cas/${platform}',
                                    self._version)
        ] + list(cmd),
        step_test_data=step_test_data,
        **kwargs)

  def download(self, step_name, digest, output_dir):
    """Downloads a directory tree from a cas server.

    Args:

      * step_name (str): name of the step.
      * digest (str): the digest of a cas tree.
      * output_dir (Path): path to an output directory.
    """
    cmd = [
        'download',
        '-cas-instance',
        self.instance,
        '-digest',
        digest,
        '-dir',
        output_dir,
    ]
    return self._run(step_name, cmd)

  def viewer_url(self, digest):
    """Return URL of cas viewer."""

    viewer_host = 'cas-viewer-dev.appspot.com'
    if self.instance.split('/')[1] != 'chromium-swarm-dev':
      viewer_host = 'cas-viewer.appspot.com'
    return 'https://{0}/{1}/blobs/{2}/tree'.format(
      viewer_host, self.instance, digest)

  def archive(self, step_name, root, *paths, log_level='info', **kwargs):
    """Archives given paths to a cas server.

    Args:
      * step_name (str): name of the step.
      * root (str|Path): root directory of archived tree, should be absolute
        path.
      * paths (list(str|Path)):
        path to archived files/dirs, should be absolute path. If empty, [root]
        will be used.
      * log_level (str): logging level to use, rarely needed but helpful for
        debugging.
      * kwargs: Additional keyword arguments to forward to "step".

    Returns:
      digest (str): digest of uploaded root directory.
    """
    self.m.path.assert_absolute(root)
    if not paths:
      paths = [root]
    for p in paths:
      self.m.path.assert_absolute(p)

    cmd = [
        'archive',
        '-log-level',
        log_level,
        '-cas-instance',
        self.instance,
        '-dump-digest',
        self.m.raw_io.output_text(),
        '-paths-json',
        self.m.json.input(
          [
            [str(root), str(self.m.path.relpath(p, root))]
            for p in paths
          ]
        ),
    ]

    # TODO(tikuta): support multiple tree upload.
    step = self._run(
        step_name,
        cmd,
        step_test_data=lambda: self.m.raw_io.test_api.output_text(
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855/0'
        ),
        **kwargs)
    digest = step.raw_io.output_text
    step.presentation.links["CAS UI"] = self.viewer_url(digest)
    return digest
