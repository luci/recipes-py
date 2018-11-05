# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with CIPD.

Depends on 'cipd' binary available in PATH:
https://godoc.org/go.chromium.org/luci/cipd/client/cmd/cipd
"""

import contextlib
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

  def __init__(self, package_name, package_root, install_mode=None,
               preserve_mtime=False, preserve_writable=False):
    """Build a new PackageDefinition.

    Args:
      * package_name (str) - the name of the CIPD package
      * package_root (Path) - the path on the current filesystem that all files
        will be relative to. e.g. if your root is /.../foo, and you add the
        file /.../foo/bar/baz.json, the final cipd package will contain
        'bar/baz.json'.
      * install_mode (None|'copy'|'symlink') - the mechanism that the cipd
        client should use when installing this package. If None, defaults to the
        platform default ('copy' on windows, 'symlink' on everything else).
      * preserve_mtime (bool) - Preserve file's modification time.
      * preserve_writable (bool) - Preserve file's writable permission bit.
    """
    check_type('package_name', package_name, str)
    check_type('package_root', package_root, Path)
    check_type('install_mode', install_mode, (type(None), str))
    if install_mode not in (None, 'copy', 'symlink'):
      raise ValueError('invalid value for install_mode: %r' % install_mode)
    self.package_name = package_name
    self.package_root = package_root
    self.install_mode = install_mode
    self.preserve_mtime = preserve_mtime
    self.preserve_writable = preserve_writable

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
      * dir_path (Path) - A path on the current filesystem under the
        package_root to a directory which should be recursively included.
      * exclusions (list(str)) - A list of regexps to exclude when scanning the
        given directory. These will be tested against the forward-slash path
        to the file relative to `dir_path`.

    Raises:
      * ValueError - dir_path is not a subdirectory of the package root.
      * re.error - one of the exclusions is not a valid regex.
    """
    check_type('dir_path', dir_path, Path)
    exclusions = exclusions or []
    check_list_type('exclusions', exclusions, str)
    self.dirs.append(self.DIR(self._rel_path(dir_path), exclusions))

  def add_file(self, file_path):
    """Add a single file to the package.

    Args:
      * file_path (Path) - A path on the current filesystem to the file you
        wish to include.

    Raises:
      * ValueError - file_path is not a subdirectory of the package root.
    """
    check_type('file_path', file_path, Path)
    self.files.append(self._rel_path(file_path))

  def add_version_file(self, ver_file_rel):
    """Instruct the cipd client to place a version file in this location when
    unpacking the package.

    Version files are JSON which look like:

        {
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
      * ver_file_rel (str) - A path string relative to the installation root.
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
      ] + (
        [{'version_file': self.version_file}]
          if self.version_file else []
      ) + (
        [{'preserve_mtime': self.preserve_mtime}]
          if self.preserve_mtime else []
      ) + (
        [{'preserve_writable': self.preserve_writable}]
          if self.preserve_writable else []
      )
    }


class EnsureFile(object):
  Package = namedtuple('Package', ['name', 'version'])

  def __init__(self):
    self.packages = {}  # dict[Path, Package]

  def add_package(self, name, version, subdir=None):
    """Add a package to the ensure file.

    Args:
      * name (str) - Name of the package, must be for right platform.
      * version (str) - Could be either instance_id, or ref, or unique tag.
      * subdir (str) - Subdirectory of root dir for the package.
    """
    self.packages.setdefault(subdir, []).append(self.Package(name, version))
    return self

  def render(self):
    """Renders the ensure file as textual representation."""
    package_list = []
    for subdir in sorted(self.packages):
      if subdir is not None:
        package_list.append('@Subdir %s' % subdir)
      for package in self.packages[subdir]:
        package_list.append('%s %s' % (package.name, package.version))
    return '\n'.join(package_list)


class CIPDApi(recipe_api.RecipeApi):
  """CIPDApi provides basic support for CIPD.

  This assumes that `cipd` (or `cipd.exe` or `cipd.bat` on windows) has been
  installed somewhere in $PATH.
  """
  PackageDefinition = PackageDefinition
  EnsureFile = EnsureFile

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
    'instance_id',
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

  def __init__(self, **kwargs):
    super(recipe_api.RecipeApi, self).__init__(**kwargs)
    self._service_account = None

  @contextlib.contextmanager
  def set_service_account(self, service_account):
    """Temporarily sets the service account used for authentication to CIPD.

    Implemented as a context manager to avoid one part of a recipe from
    overwriting another's specified service account.

    Args:
      * service_account(service_account.api.ServiceAccount): Service account to
          use for authentication.
    """
    assert isinstance(service_account, self.m.service_account.ServiceAccount), \
        'Service account must be of type ' \
        'recipe_module.service_account.ServiceAccount. Was %s' % (
            type(service_account))
    prev_service_account = self._service_account
    self._service_account = service_account
    try:
      yield
    finally:
      self._service_account = prev_service_account

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
      * pkg_path (str) - The package subpath.
      * reader (bool) - Check for READER role.
      * writer (bool) - Check for WRITER role.
      * owner (bool) - Check for OWNER role.

    Returns True if the caller has given roles, False otherwise.
    """
    cmd = [
        'acl-check',
        pkg_path
    ] + self._service_account_opts()
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

  def _build(self, pkg_name, pkg_def_file_or_placeholder, output_package,
             pkg_vars=None, compression_level=None):
    if pkg_vars:
      check_dict_type('pkg_vars', pkg_vars, str, str)

    cmd = [
      'pkg-build',
      '-pkg-def', pkg_def_file_or_placeholder,
      '-out', output_package,
      '-hash-algo', 'sha256',
    ] + self._cli_options((), (), pkg_vars)
    if compression_level:
      cmd.extend(['-compression-level', int(compression_level)])

    step_result = self._run(
        'build %s' % pkg_name, cmd,
        step_test_data=lambda: self.test_api.example_build(pkg_name)
    )
    result = step_result.json.output['result']
    return self.Pin(**result)

  def build_from_yaml(self, pkg_def, output_package, pkg_vars=None,
                      compression_level=None):
    """Builds a package based on on-disk YAML package definition file.

    Args:
      * pkg_def (Path) - The path to the yaml file.
      * output_package (Path) - The file to write the package to.
      * pkg_vars (dict[str]str) - A map of var name -> value to use for vars
        referenced in package definition file.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, Path)
    return self._build(
        self.m.path.basename(pkg_def),
        pkg_def,
        output_package,
        pkg_vars,
        compression_level,
    )

  def build_from_pkg(self, pkg_def, output_package,
                     compression_level=None):
    """Builds a package based on a PackageDefinition object.

    Args:
      * pkg_def (PackageDefinition) - The description of the package we want to
        create.
      * output_package (Path) - The file to write the package to.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, PackageDefinition)
    return self._build(
        pkg_def.package_name,
        self.m.json.input(pkg_def.to_jsonish()),
        output_package,
        compression_level=compression_level,
    )

  def build(self, input_dir, output_package, package_name,
            compression_level=None, install_mode=None, preserve_mtime=False,
            preserve_writable=False):
    """Builds, but does not upload, a cipd package from a directory.

    Args:
      * input_dir (Path) - The directory to build the package from.
      * output_package (Path) - The file to write the package to.
      * package_name (str) - The name of the cipd package as it would appear
        when uploaded to the cipd package server.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).
      * install_mode (None|'copy'|'symlink') - The mechanism that the cipd
        client should use when installing this package. If None, defaults to the
        platform default ('copy' on windows, 'symlink' on everything else).
      * preserve_mtime (bool) - Preserve file's modification time.
      * preserve_writable (bool) - Preserve file's writable permission bit.

    Returns the CIPDApi.Pin instance.
    """
    assert not compression_level or isinstance(compression_level, int)
    assert not install_mode or install_mode in ['copy', 'symlink']

    cmd = [
      'pkg-build',
      '-in', input_dir,
      '-name', package_name,
      '-out', output_package,
      '-hash-algo', 'sha256',
    ]
    if compression_level:
      cmd.extend(['-compression-level', int(compression_level)])
    if install_mode:
      cmd.extend(['-install-mode', install_mode])
    if preserve_mtime:
      cmd.append('-preserve-mtime')
    if preserve_writable:
      cmd.append('-preserve-writable')
    step_result = self._run(
        'build %s' % self.m.path.basename(package_name), cmd,
        step_test_data=lambda: self.test_api.example_build(package_name)
    )
    result = step_result.json.output['result']
    return self.Pin(**result)

  def _service_account_opts(self):
    if self._service_account and self._service_account.key_path:
      return ['-service-account-json', self._service_account.key_path]
    return []

  def _cli_options(self, refs, tags, pkg_vars):
    """Computes a list of CIPD CLI -ref, -tag, and -pkg-var options given a
    sequence of refs, a dict of tags, and a dict of pkg_vars."""
    ret = []
    if refs:
      for ref in refs:
        ret.extend(['-ref', ref])
    if tags:
      for tag, value in sorted(tags.items()):
        ret.extend(['-tag', '%s:%s' % (tag, value)])
    if pkg_vars:
      for var_name, value in sorted(pkg_vars.items()):
        ret.extend(['-pkg-var', '%s:%s' % (var_name, value)])
    return ret

  def register(self, package_name, package_path, refs=(), tags=None):
    """Uploads and registers package instance in the package repository.

    Args:
      * package_name (str) - The name of the cipd package.
      * package_path (Path) - The path to package instance file.
      * refs (seq[str]) - A list of ref names to set for the package instance.
      * tags (dict[str]basestring) - A map of tag name -> value to set for the package
                              instance.

    Returns:
      The CIPDApi.Pin instance.
    """
    cmd = [
      'pkg-register', package_path
    ] + self._cli_options(refs, tags, ()) + self._service_account_opts()
    step_result = self._run(
        'register %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_register(package_name)
    )
    return self.Pin(**step_result.json.output['result'])

  def _create(self, pkg_name, pkg_def_file_or_placeholder, refs=None, tags=None,
              pkg_vars=None, compression_level=None):
    refs = [] if refs is None else refs
    tags = {} if tags is None else tags
    pkg_vars = {} if pkg_vars is None else pkg_vars
    check_list_type('refs', refs, str)
    check_dict_type('tags', tags, str, basestring)
    check_dict_type('pkg_vars', pkg_vars, str, str)
    cmd = [
      'create',
      '-pkg-def', pkg_def_file_or_placeholder,
      '-hash-algo', 'sha256',
    ] + self._cli_options(refs, tags, pkg_vars) + self._service_account_opts()
    if compression_level:
      cmd.extend(['-compression-level', int(compression_level)])
    step_result = self._run(
      'create %s' % pkg_name, cmd,
      step_test_data=lambda: self.test_api.m.json.output({
        'result': self.test_api.make_pin(pkg_name),
      }))
    result = step_result.json.output['result']
    step_result.presentation.step_text = '</br>pkg: %(package)s' % result
    step_result.presentation.step_text += '</br>id: %(instance_id)s' % result
    return self.Pin(**result)

  def create_from_yaml(self, pkg_def, refs=None, tags=None, pkg_vars=None,
                       compression_level=None):
    """Builds and uploads a package based on on-disk YAML package definition
    file.

    This builds and uploads the package in one step.

    Args:
      * pkg_def (Path) - The path to the yaml file.
      * refs (list[str]) - A list of ref names to set for the package instance.
      * tags (dict[str]str) - A map of tag name -> value to set for the
        package instance.
      * pkg_vars (dict[str]str) - A map of var name -> value to use for vars
        referenced in package definition file.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, Path)
    return self._create(
        self.m.path.basename(pkg_def), pkg_def, refs, tags, pkg_vars,
        compression_level)

  def create_from_pkg(self, pkg_def, refs=None, tags=None,
                      compression_level=None):
    """Builds and uploads a package based on a PackageDefinition object.

    This builds and uploads the package in one step.

    Args:
      * pkg_def (PackageDefinition) - The description of the package we want to
        create.
      * refs (list[str]) - A list of ref names to set for the package instance.
      * tags (dict[str]str) - A map of tag name -> value to set for the
        package instance.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, PackageDefinition)
    return self._create(
        pkg_def.package_name, self.m.json.input(pkg_def.to_jsonish()), refs,
        tags, compression_level=compression_level)

  def ensure(self, root, ensure_file):
    """Ensures that packages are installed in a given root dir.

    Args:
      * root (Path) - Path to installation site root directory.
      * ensure_file (EnsureFile) - List of packages to install.

    Returns the map of subdirectories to CIPDApi.Pin instances.
    """
    check_type('ensure_file', ensure_file, EnsureFile)
    cmd = [
      'ensure',
      '-root', root,
      '-ensure-file', self.m.raw_io.input(ensure_file.render())
    ]
    step_result = self._run(
        'ensure_installed', cmd,
        step_test_data=lambda: self.test_api.example_ensure(ensure_file)
    )
    return {
        subdir: [self.Pin(**pin) for pin in pins]
        for subdir, pins in step_result.json.output['result'].iteritems()
    }

  def set_tag(self, package_name, version, tags):
    """Tags package of a specific version.

    Args:
      * package_name (str) - The name of the cipd package.
      * version (str) - The package version to resolve. Could also be itself a
        tag or ref.
      * tags (dict[str]str) - A map of tag name -> value to set for the
        package instance.

    Returns the CIPDApi.Pin instance.
    """
    cmd = [
      'set-tag', package_name,
      '-version', version,
    ] + self._cli_options((), tags, ())

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
      * package_name (str) - The name of the cipd package.
      * version (str) - The package version to point the ref to.
      * refs (list[str]) - A list of ref names to set for the package instance.

    Returns the CIPDApi.Pin instance.
    """
    cmd = [
      'set-ref', package_name,
      '-version', version,
    ] + self._cli_options(refs, (), ()) + self._service_account_opts()

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
      * package_name (str) - The name of the cipd package.
      * tag (str) - The cipd package tag.

    Returns the list of CIPDApi.Pin instances.
    """

    assert ':' in tag, 'tag must be in a form "k:v"'

    cmd = [
      'search', package_name,
      '-tag', tag,
    ] + self._service_account_opts()

    step_result = self._run(
        'cipd search %s %s' % (package_name, tag),
        cmd,
        step_test_data=lambda: self.test_api.example_search(package_name)
    )
    return [self.Pin(**pin) for pin in step_result.json.output['result'] or []]

  def describe(self, package_name, version,
               test_data_refs=None, test_data_tags=None):
    """Returns information about a pacakge instance given its version:
    who uploaded the instance and when and a list of attached tags.

    Args:
      * package_name (str) - The name of the cipd package.
      * version (str) - The package version to point the ref to.
      * test_data_refs (seq[str]) - The list of refs for this call to return
        by default when in test mode.
      * test_data_tags (seq[str]) - The list of tags (in 'name:val' form) for
        this call to return by default when in test mode.

    Returns the CIPDApi.Description instance describing the package.
    """
    step_result = self._run(
        'cipd describe %s' % package_name,
        ['describe', package_name, '-version', version],
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
        refs=[self.Ref(**ref) for ref in result.get('refs', ())],
        tags=[self.Tag(**tag) for tag in result.get('tags', ())],
    )

  def pkg_fetch(self, destination, package_name, version):
    """Downloads the specified package to destination.

    ADVANCED METHOD: You shouldn't need this unless you're doing advanced things
    with CIPD. Typically you should use the `ensure` method here to
    fetch+install packages to the disk.

    Args:
      * destination (Path) - Path to a file location which will be (over)written
        with the package file contents.
      * package_name (str) - The package name (or pattern with e.g.
        ${platform})
      * version (str) - The CIPD version to fetch

    Returns a Pin for the downloaded package.
    """
    check_type('destination', destination, Path)
    check_type('package_name', package_name, str)
    check_type('version', version, str)
    cmd = ['pkg-fetch', package_name, '-version', version, '-out', destination]
    cmd += self._service_account_opts()
    step_result = self._run(
      'cipd pkg-fetch %s' % package_name,
      cmd,
      step_test_data=lambda: self.test_api.example_pkg_fetch(
        package_name, version)
    )
    ret = self.Pin(**step_result.json.output['result'])
    step_result.presentation.step_text = '%s %s' % (
        ret.package, ret.instance_id)
    return ret

  def pkg_deploy(self, root, package_file):
    """Deploys the specified package to root.

    ADVANCED METHOD: You shouldn't need this unless you're doing advanced things
    with CIPD. Typically you should use the `ensure` method here to
    fetch+install packages to the disk.

    Args:
      * package_file (Path) - Path to a package file to install.
      * root (Path) - Path to a CIPD root.

    Returns a Pin for the deployed package.
    """
    check_type('root', root, Path)
    check_type('package_file', package_file, Path)
    step_result = self._run(
      'cipd pkg-deploy %s' % package_file,
      ['pkg-deploy', package_file, '-root', root],
      step_test_data=lambda: self.test_api.example_pkg_deploy(
        'pkg/name/of/'+package_file.pieces[-1],
        'version/of/'+package_file.pieces[-1])
    )
    return self.Pin(**step_result.json.output['result'])
