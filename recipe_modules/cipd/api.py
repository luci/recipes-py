# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with CIPD.

Depends on 'cipd' binary available in PATH:
https://godoc.org/go.chromium.org/luci/cipd/client/cmd/cipd
"""

import re

from collections import namedtuple

from recipe_engine import recipe_api
from recipe_engine.config_types import Path


def check_type(name, var, expect):
  if not isinstance(var, expect):  # pragma: no cover
    raise TypeError('%s is not %s: %r (%s)' % (
      name, type(expect).__name__, var, type(var).__name__))


def check_list_type(name, var, expect_inner):
  check_type(name, var, list)
  for i, itm in enumerate(var):
    check_type('%s[%d]' % (name, i), itm, expect_inner)


def check_dict_type(name, var, expect_key, expect_value):
  check_type(name, var, dict)
  for key, value in var.iteritems():
    check_type('%s: key' % name, key, expect_key)
    check_type('%s[%s]' % (name, key), value, expect_value)


class PackageDefinition(object):
  DIR = namedtuple('DIR', ['path', 'exclusions'])

  def __init__(self, package_name, package_root, install_mode=None):
    """Build a new PackageDefinition.

    Args:
      package_name (str) - the name of the CIPD package
      package_root (Path) - the path on the current filesystem that all files
        will be relative to. e.g. if your root is /.../foo, and you add the
        file /.../foo/bar/baz.json, the final cipd package will contain
        'bar/baz.json'.
      install_mode (None|'copy'|'symlink') - the mechanism that the cipd client
        should use when installing this package. If None, defaults to the
        platform default ('copy' on windows, 'symlink' on everything else).
    """
    check_type('package_name', package_name, str)
    check_type('package_root', package_root, Path)
    check_type('install_mode', install_mode, (type(None), str))
    if install_mode not in (None, 'copy', 'symlink'):
      raise ValueError('invalid value for install_mode: %r' % install_mode)
    self.package_name = package_name
    self.package_root = package_root
    self.install_mode = install_mode

    self.dirs = []  # list(DIR)
    self.files = []  # list(Path)
    self.version_file = None  # str?

  def _rel_path(self, path):
    """Returns a forward-slash-delimited version of `path` which is relative to
    the package root. Will raise ValueError if path is not inside the root."""
    if path == self.package_root:
      return '.'
    if not self.package_root.is_parent_of(path):
      raise ValueError(
          'path %r is not the package root %r and not a child thereof' %
          (path, self.package_root))
    # we know that root has the same base and some prefix of path
    return '/'.join(path.pieces[len(self.package_root.pieces):])

  def add_dir(self, dir_path, exclusions=None):
    """Recursively add a directory to the package.

    Args:
      dir_path (Path) - A path on the current filesystem under the
        package_root to a directory which should be recursively included.
      exclusions (list(str)) - A list of regexps to exclude when scanning the
        given directory. These will be tested against the forward-slash path
        to the file relative to `dir_path`.

    Raises:
      ValueError - dir_path is not a subdirectory of the package root.
      re.error - one of the exclusions is not a valid regex.
    """
    check_type('dir_path', dir_path, Path)
    exclusions = exclusions or []
    check_list_type('exclusions', exclusions, str)
    self.dirs.append(self.DIR(self._rel_path(dir_path), exclusions))

  def add_file(self, file_path):
    """Add a single file to the package.

    Args:
      file_path (Path) - A path on the current filesystem to the file you
        wish to include.

    Raises:
      ValueError - file_path is not a subdirectory of the package root.
    """
    check_type('file_path', file_path, Path)
    self.files.append(self._rel_path(file_path))

  def add_version_file(self, ver_file_rel):
    """Instruct the cipd client to place a version file in this location when
    unpacking the package.

    Version files are JSON which look like: {
      "package_name": "infra/tools/cipd/android-amd64",
      "instance_id": "433bfdf86c0bb82d1eee2d1a0473d3709c25d2c4"
    }

    The convention is to pick a location like '.versions/<name>.cipd_version'
    so that a given cipd installation root might have a .versions folder full
    of these files, one per package. This file allows executables contained
    in the package to look for and report this file, allowing them to display
    version information about themselves. <name> could be the name of the
    binary tool, like 'cipd' in the example above.

    A version file may be specifed exactly once per package.

    Args:
      ver_file_rel (str) - A path string relative to the installation root.
        Should be specified in posix style (forward/slashes).
    """
    check_type('ver_file_rel', ver_file_rel, str)
    if self.version_file is not None:
      raise ValueError('add_version_file() may only be used once.')
    self.version_file = ver_file_rel

  def to_jsonish(self):
    """Returns a JSON representation of this PackageDefinition."""
    return {
      'package': self.package_name,
      'root': str(self.package_root),
      'install_mode': self.install_mode or '',
      'data': [
        {'file': str(f)}
        for f in self.files
      ] + [
        {'dir': str(d.path), 'exclude': d.exclusions}
        for d in self.dirs
      ] + ([{'version_file': self.version_file}] if self.version_file else [])
    }


class CIPDApi(recipe_api.RecipeApi):
  """CIPDApi provides basic support for CIPD.

  This assumes that `cipd` (or `cipd.exe` or `cipd.bat` on windows) has been
  installed somewhere in $PATH.
  """
  PackageDefinition = PackageDefinition

  # A CIPD pin.
  Pin = namedtuple('Pin', [
    'package',
    'instance_id',
  ])

  # A CIPD ref.
  Ref = namedtuple('Ref', [
    'ref',
    'modified_by',
    'modified_ts',
  ])

  # A CIPD tag.
  Tag = namedtuple('Tag', [
    'tag',
    'registered_by',
    'registered_ts',
  ])

  # A CIPD package description.
  Description = namedtuple('Description', [
    'pin',
    'registered_by',
    'registered_ts',
    'refs',
    'tags',
  ])

  class Error(recipe_api.StepFailure):
    def __init__(self, step_name, message):
      reason = 'CIPD(%r) failed with: %s' % (step_name, message)
      super(CIPDApi.Error, self).__init__(reason)

  @property
  def executable(self):
    return 'cipd' + ('.bat' if self.m.platform.is_win else '')

  def _run(self, name, args, step_test_data=None):
    cmd = [self.executable] + args + ['-json-output', self.m.json.output()]
    try:
      return self.m.step(name, cmd, step_test_data=step_test_data)
    except self.m.step.StepFailure:
      step_result = self.m.step.active_result
      if 'error' in step_result.json.output:
        raise self.Error(name, step_result.json.output['error'])
      else: # pragma: no cover
        raise

  def acl_check(self, pkg_path, reader=True, writer=False, owner=False):
    """Checks whether the caller has a given roles in a package.

    Args:
      pkg_path (str) - The package subpath.
      reader (bool) - Check for READER role.
      writer (bool) - Check for WRITER role.
      owner (bool) - Check for OWNER role.

    Returns:
      True if the caller has given roles, False otherwise.
    """
    cmd = [
        'acl-check',
        pkg_path
    ]
    if reader:
      cmd.append('-reader')
    if writer:
      cmd.append('-writer')
    if owner:
      cmd.append('-owner')
    step_result = self._run(
        'acl-check %s' % pkg_path, cmd,
        step_test_data=lambda: self.test_api.example_acl_check(pkg_path)
    )
    return step_result.json.output['result']

  def _build(self, pkg_name, pkg_def_file_or_placeholder, output_package):
    step_result = self._run(
        'build %s' % pkg_name,
        [
          'pkg-build',
          '-pkg-def', pkg_def_file_or_placeholder,
          '-out', output_package,
        ],
        step_test_data=lambda: self.test_api.example_build(pkg_name)
    )
    result = step_result.json.output['result']
    return self.Pin(**result)

  def build_from_yaml(self, pkg_def, output_package):
    """Builds a package based on on-disk YAML package definition file.

    Args:
      pkg_def (Path) - The path to the yaml file.
      output_package (Path) - The file to write the package to.

    Returns:
      The CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, Path)
    return self._build(
        self.m.path.basename(pkg_def),
        pkg_def,
        output_package
    )

  def build_from_pkg(self, pkg_def, output_package):
    """Builds a package based on a PackageDefinition object.

    Args:
      pkg_def (PackageDefinition) - The description of the package we want to
        create.
      output_package (Path) - The file to write the package to.

    Returns:
      The CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, PackageDefinition)
    return self._build(
        pkg_def.package_name,
        self.m.json.input(pkg_def.to_jsonish()),
        output_package
    )

  def build(self, input_dir, output_package, package_name, install_mode=None):
    """Builds, but does not upload, a cipd package from a directory.

    Args:
      input_dir (Path) - The directory to build the package from.
      output_package (Path) - The file to write the package to.
      package_name (str) - The name of the cipd package as it would appear when
        uploaded to the cipd package server.
      install_mode (None|'copy'|'symlink') - The mechanism that the cipd client
        should use when installing this package. If None, defaults to the
        platform default ('copy' on windows, 'symlink' on everything else).

    Returns:
      The CIPDApi.Pin instance.
    """
    assert not install_mode or install_mode in ['copy', 'symlink']

    step_result = self._run(
        'build %s' % self.m.path.basename(package_name),
        [
          'pkg-build',
          '-in', input_dir,
          '-name', package_name,
          '-out', output_package,
        ] + (
          ['-install-mode', install_mode] if install_mode else []
        ),
        step_test_data=lambda: self.test_api.example_build(package_name)
    )
    result = step_result.json.output['result']
    return self.Pin(**result)

  def register(self, package_name, package_path, refs=(), tags={}):
    """Uploads and registers package instance in the package repository.

    Args:
      package_name (str) - The name of the cipd package.
      package_path (Path) - The path to package instance file.
      refs (list(str)) - A list of ref names to set for the package instance.
      tags (dict(str, str)) - A map of tag name -> value to set for the package
                              instance.

    Returns:
      The CIPDApi.Pin instance.
    """
    cmd = [
      'pkg-register', package_path,
    ]
    if refs:
      for ref in refs:
        cmd.extend(['-ref', ref])
    if tags:
      for tag, value in sorted(tags.items()):
        cmd.extend(['-tag', '%s:%s' % (tag, value)])
    step_result = self._run(
        'register %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_register(package_name)
    )
    return self.Pin(**step_result.json.output['result'])

  def _create(self, pkg_name, pkg_def_file_or_placeholder, refs=(), tags={}):
    refs = refs or []
    tags = tags or {}
    check_list_type('refs', refs, str)
    check_dict_type('tags', tags, str, str)
    cmd = [
      'create',
      '-pkg-def', pkg_def_file_or_placeholder,
    ]
    for ref in refs:
      cmd.extend(['-ref', ref])
    for tag, value in sorted(tags.items()):
      cmd.extend(['-tag', '%s:%s' % (tag, value)])
    step_result = self._run(
      'create %s' % pkg_name, cmd,
      step_test_data=lambda: self.test_api.m.json.output({
        'result': self.test_api.make_pin(pkg_name),
      }))
    result = step_result.json.output['result']
    step_result.presentation.step_text = '</br>pkg: %(package)s' % result
    step_result.presentation.step_text += '</br>id: %(instance_id)s' % result
    return self.Pin(**result)

  def create_from_yaml(self, pkg_def, refs=(), tags={}):
    """Builds and uploads a package based on on-disk YAML package definition
    file.

    This builds and uploads the package in one step.

    Args:
      pkg_def (Path) - The path to the yaml file.
      refs (list(str)) - A list of ref names to set for the package instance.
      tags (dict(str, str)) - A map of tag name -> value to set for the package
                              instance.

    Returns:
      The CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, Path)
    return self._create(self.m.path.basename(pkg_def), pkg_def, refs, tags)

  def create_from_pkg(self, pkg_def, refs=(), tags={}):
    """Builds and uploads a package based on a PackageDefinition object.

    This builds and uploads the package in one step.

    Args:
      pkg_def (PackageDefinition) - The description of the package we want to
        create.
      refs (list(str)) - A list of ref names to set for the package instance.
      tags (dict(str, str)) - A map of tag name -> value to set for the package
                              instance.

    Returns:
      The CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, PackageDefinition)
    return self._create(
      pkg_def.package_name, self.m.json.input(pkg_def.to_jsonish()), refs, tags)

  def ensure(self, root, packages):
    """Ensures that packages are installed in a given root dir.

    packages must be a mapping from package name to its version, where
      * name must be for right platform,
      * version could be either instance_id, or ref, or unique tag.

    Returns:
      The list of CIPDApi.Pin instances.
    """
    package_list = ['%s %s' % (name, version)
                    for name, version in sorted(packages.items())]
    ensure_file = self.m.raw_io.input('\n'.join(package_list))
    cmd = [
      'ensure',
      '-root', root,
      '-ensure-file', ensure_file,
    ]
    step_result = self._run(
        'ensure_installed', cmd,
        step_test_data=lambda: self.test_api.example_ensure(packages)
    )
    return [self.Pin(**pin) for pin in step_result.json.output['result']['']]

  def set_tag(self, package_name, version, tags):
    """Tags package of a specific version.

    Args:
      package_name (str) - The name of the cipd package.
      version (str) - The package version to resolve. Could also be itself a tag
                      or ref.
      tags (dict(str, str)) - A map of tag name -> value to set for the package
                              instance.

    Returns:
      The CIPDApi.Pin instance.
    """
    cmd = [
      'set-tag', package_name,
      '-version', version,
    ]
    for tag, value in sorted(tags.items()):
      cmd.extend(['-tag', '%s:%s' % (tag, value)])

    step_result = self._run(
        'cipd set-tag %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_set_tag(
            package_name, version
        )
    )
    result = step_result.json.output['result']
    return self.Pin(**result['pin'])

  def set_ref(self, package_name, version, refs):
    """Moves a ref to point to a given version.

    Args:
      package_name (str) - The name of the cipd package.
      version (str) - The package version to point the ref to.
      refs (list(str)) - A list of ref names to set for the package instance.

    Returns:
      The CIPDApi.Pin instance.
    """
    cmd = [
      'set-ref', package_name,
      '-version', version,
    ]
    for r in refs:
      cmd.extend(['-ref', r])

    step_result = self._run(
        'cipd set-ref %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_set_ref(
            package_name, version
        )
    )
    result = step_result.json.output['result']
    return self.Pin(**result['pin'])

  def search(self, package_name, tag):
    """Searches for package instances by tag, optionally constrained by package
    name.

    Args:
      package_name (str) - The name of the cipd package.
      tag (str) - The cipd package tag.

    Returns:
      The list of CIPDApi.Pin instances.
    """

    assert ':' in tag, 'tag must be in a form "k:v"'

    cmd = [
      'search', package_name,
      '-tag', tag,
    ]

    step_result = self._run(
        'cipd search %s %s' % (package_name, tag),
        cmd,
        step_test_data=lambda: self.test_api.example_search(package_name)
    )
    return [self.Pin(**pin) for pin in step_result.json.output['result']]

  def describe(self, package_name, version,
               test_data_refs=(), test_data_tags={}):
    """Returns information about a pacakge instance given its version:
    who uploaded the instance and when and a list of attached tags.

    Args:
      package_name (str) - The name of the cipd package.
      version (str) - The package version to point the ref to.

    Returns:
      The CIPDApi.Description instance describing the package.
    """
    cmd = [
      'describe', package_name,
      '-version', version,
    ]

    step_result = self._run(
        'cipd describe %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_describe(
            package_name, version,
            test_data_refs=test_data_refs,
            test_data_tags=test_data_tags
        )
    )
    result = step_result.json.output['result']
    return self.Description(
        pin=self.Pin(**result['pin']),
        registered_by=result['registered_by'],
        registered_ts=['registered_ts'],
        refs=[self.Ref(*ref) for ref in result['refs']],
        tags=[self.Tag(*tag) for tag in result['tags']],
    )
