# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with cas client."""

import os

from recipe_engine import recipe_api

# Take revision from
# https://ci.chromium.org/p/infra-internal/g/infra-packagers/console
DEFAULT_CIPD_VERSION = 'git_revision:9ba67f2876f4a3455a51433de7cc3e869d81b280'


class CasApi(recipe_api.RecipeApi):
  """A module for interacting with cas client."""

  def __init__(self, **kwargs):
    super(CasApi, self).__init__(**kwargs)

    self._instance = None

  @property
  def instance(self):
    if self._instance:
      return self._instance

    if self._test_data.enabled:
      swarming_server= 'https://example-cas-server.appspot.com'
    else: # pragma: no cover
      # Extract default instance from swarming task env.
      # See https://chromium.googlesource.com/infra/luci/luci-py/+/1c201e5909b61b859b82d16cfff15267d1c0efea/appengine/swarming/doc/Magic-Values.md#client-tool-environment-variables
      swarming_server = os.environ['SWARMING_SERVER']
    project = swarming_server[len('https://'):-len('.appspot.com')]

    # Set full instance name if only project ID is given.
    self._instance = 'projects/%s/instances/default_instance' % project

    return self._instance

  @property
  def _version(self):
    version = DEFAULT_CIPD_VERSION
    if self.m.runtime.is_experimental:
      version = 'latest'
    elif self._test_data.enabled:
      version = 'cas_module_pin'
    return version

  def _run(self, name, cmd, step_test_data=None):
    """Returns a cas command step.

    Args:
      * name: (str): name of the step.
      * cmd (list(str|Path)): cas client subcommand to run.
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

  def archive(self, step_name, root, *paths):
    """Archives given paths to a cas server.

    Args:
      * step_name (str): name of the step.
      * root (str|Path): root directory of archived tree, should be absolute
        path.
      * paths (list(str|Path)):
        path to archived files/dirs, should be absolute path.

    Returns:
      digest (str): digest of uploaded root directory.
    """
    self.m.path.assert_absolute(root)
    cmd = [
        'archive',
        '-cas-instance',
        self.instance,
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
    return self._run(
        step_name,
        cmd,
        step_test_data=lambda: self.m.raw_io.test_api.output_text(
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855/0'
        )).raw_io.output_text
