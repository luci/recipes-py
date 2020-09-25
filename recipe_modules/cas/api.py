# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""API for interacting with cas client."""

from recipe_engine import recipe_api

# Take revision from
# https://ci.chromium.org/p/infra-internal/g/infra-packagers/console
DEFAULT_CIPD_VERSION = 'git_revision:71f4d6c39179d79278ed4114d7044290ca0a25cf'


class CasApi(recipe_api.RecipeApi):
  """A module for interacting with cas client."""

  def __init__(self, props, **kwargs):
    """
    'instance' in props needs to be a GCP project ID to use default
    instance, or full RBE-CAS instance name
    e.g. `projects/<project name>/instances/<instance name>`.
    """
    super(CasApi, self).__init__(**kwargs)
    default_instance = None
    if self._test_data.enabled:
      default_instance = 'example-cas-server'
    self._instance = props.instance or default_instance

  @property
  def _version(self):
    version = DEFAULT_CIPD_VERSION
    if self.m.runtime.is_experimental:
      version = 'latest'
    elif self._test_data.enabled:
      version = 'cas_module_pin'
    return version

  def _run(self, name, cmd, step_test_data=None):
    """Return a cas command step.
    Args:
      name: (str): name of the step.
      cmd (list(str|Path)): cas client subcommand to run.
    """
    return self.m.step(
        name,
        [
            self.m.cipd.ensure_tool('infra/tools/luci/cas/${platform}',
                                    self._version)
        ] + list(cmd),
        step_test_data=step_test_data,
        infra_step=True)

  def download(self, step_name, digest, output_dir):
    """Downloads a directory tree from a cas server.

    Args:
      step_name (str): name of the step.
      digest (str): the digest of a cas tree.
      output_dir (Path): path to an output directory.
    """
    cmd = [
        'download',
        '-cas-instance',
        self._instance,
        '-digest',
        digest,
        '-dir',
        output_dir,
    ]
    return self._run(step_name, cmd)

  def archive(self, step_name, root, *paths):
    """Archives given paths to a cas server.

    Args:
      step_name (str): name of the step.
      root (str|Path): root directory of archived tree, should be absolute path.
      paths (list(str|Path)):
        path to archived files/dirs, should be absolute path.

    Returns:
      digest (str): digest of uploaded root directory.
    """
    self.m.path.assert_absolute(root)
    cmd = [
        'archive',
        '-cas-instance',
        self._instance,
        '-dump-digest',
        self.m.raw_io.output_text(),
    ]
    for p in paths:
      self.m.path.assert_absolute(p)
      cmd.extend(
          ['-paths',
           str(root) + ':' + str(self.m.path.relpath(p, root))])

    # TODO(crbug.com/1128250): add link to viewer.
    # TODO(tikuta): support multiple tree upload.
    return self._run(step_name, cmd).raw_io.output_text
