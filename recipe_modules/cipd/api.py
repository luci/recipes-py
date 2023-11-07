# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with CIPD.

Depends on 'cipd' binary available in PATH:
https://godoc.org/go.chromium.org/luci/cipd/client/cmd/cipd
"""

from future.utils import iteritems
from past.builtins import basestring
from typing import *

import contextlib
import hashlib

from collections import defaultdict, namedtuple
try:
  from collections.abc import Mapping, Sequence
except ImportError:  # pragma: no cover
  # Required to support Python < 3.3.
  # pylint: disable=deprecated-class
  from collections import Mapping, Sequence

from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from recipe_engine.recipe_utils import check_type, check_list_type, check_dict_type

CIPD_SERVER_URL = 'https://chrome-infra-packages.appspot.com'


class PackageDefinition(object):
  DIR = namedtuple('DIR', ['path', 'exclusions'])

  def __init__(self,
               package_name,
               package_root,
               install_mode=None,
               preserve_mtime=False,
               preserve_writable=False):
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
    check_type('package_name', package_name, basestring)
    check_type('package_root', package_root, Path)
    check_type('install_mode', install_mode, (type(None), basestring))
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
    check_list_type('exclusions', exclusions, basestring)
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

    A version file may be specified exactly once per package.

    Args:
      * ver_file_rel (str) - A path string relative to the installation root.
        Should be specified in posix style (forward/slashes).
    """
    check_type('ver_file_rel', ver_file_rel, basestring)
    if self.version_file is not None:
      raise ValueError('add_version_file() may only be used once.')
    self.version_file = ver_file_rel

  def to_jsonish(self):
    """Returns a JSON representation of this PackageDefinition."""
    output = {
        'package':
            self.package_name,
        'root':
            str(self.package_root),
        'install_mode':
            self.install_mode or '',
        'data': [{
            'file': str(f)
        } for f in self.files] + [{
            'dir': str(d.path),
            'exclude': d.exclusions
        } for d in self.dirs] + ([{
            'version_file': self.version_file
        }] if self.version_file else [])
    }
    if self.preserve_mtime:
      output['preserve_mtime'] = self.preserve_mtime
    if self.preserve_writable:
      output['preserve_writable'] = self.preserve_writable
    return output


class EnsureFile(object):
  Package = namedtuple('Package', ['name', 'version'])

  def __init__(self):
    self.packages = defaultdict(list)  # dict[Path, List[Package]]

  def add_package(self, name, version, subdir=''):
    """Add a package to the ensure file.

    Args:
      * name (str) - Name of the package, must be for right platform.
      * version (str) - Could be either instance_id, or ref, or unique tag.
      * subdir (str) - Subdirectory of root dir for the package.
    """
    self.packages[subdir].append(self.Package(name, version))
    return self

  def render(self):
    """Renders the ensure file as textual representation."""
    package_list = []
    for subdir in sorted(self.packages):
      if subdir:
        package_list.append('@Subdir %s' % subdir)
      for package in self.packages[subdir]:
        package_list.append('%s %s' % (package.name, package.version))
    return '\n'.join(package_list)


class Metadata(object):
  def __init__(self, key, value=None, value_from_file=None, content_type=None):
    """Constructs a metadata entry to attach to a package instance.

    Each entry has a key (doesn't have to be unique), a value (supplied either
    directly as a string or read from a file), and a content type. The content
    type can be omitted, the CIPD client will try to guess it in this case.

    Args:
      * key (str) - the metadata key.
      * value (str|None) - the literal metadata value. Can't be used together
        with 'value_from_file'.
      * value_from_file (Path|None) - the path to read the value from. Can't be
        used together with 'value'.
      * content-type (str|None) - a content type of the metadata value
        (e.g. "application/json" or "text/plain"). Will be guessed if not given.
    """
    check_type('key', key, basestring)
    if value is not None:
      check_type('value', value, basestring)
    if value_from_file is not None:
      check_type('value_from_file', value_from_file, Path)
    if content_type is not None:
      check_type('content_type', content_type, basestring)
    if not value and not value_from_file:  # pragma: no cover
      raise ValueError('Either "value" or "value_from_file" should be given')
    if value and value_from_file:  # pragma: no cover
      raise ValueError(
          'Only one of "value" or "value_from_file" should be given, not both')
    self._key = key
    self._value = value
    self._value_from_file = value_from_file
    self._content_type = content_type

  def _as_cli_flag(self):
    key = self._key
    if self._content_type:
      key += '(%s)' % self._content_type
    if self._value_from_file:
      return ['-metadata-from-file', '%s:%s' % (key, self._value_from_file)]
    return ['-metadata', '%s:%s' % (key, self._value)]


class CIPDApi(recipe_api.RecipeApi):
  """CIPDApi provides basic support for CIPD.

  This assumes that `cipd` (or `cipd.exe` or `cipd.bat` on windows) has been
  installed somewhere in $PATH.

  Attributes:
    * max_threads (int) - Number of worker threads for extracting packages.
      If 0, uses CPU count.
  """
  PackageDefinition = PackageDefinition
  EnsureFile = EnsureFile
  Metadata = Metadata

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

  # A CIPD package instance.
  Instance = namedtuple('Instance', [
      'pin',
      'registered_by',
      'registered_ts',
      'refs',
  ])

  class Error(recipe_api.StepFailure):

    def __init__(self, step_name, message):
      reason = 'CIPD(%r) failed with: %s' % (step_name, message)
      super(CIPDApi.Error, self).__init__(reason)

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self.max_threads = 0  # 0 means use system CPU count.
    # A mapping from (package, version) to Future for packages installed
    # via `ensure_tool()`. The Future has no returned value and just used to
    # synchronize 'ensure' actions.
    self._installed_tool_package_futures = {}

  @contextlib.contextmanager
  def cache_dir(self, directory):
    """Sets the cache dir to use with CIPD by setting the $CIPD_CACHE_DIR
    environment variable.

    If directory is "None", will use no cache directory.
    """
    if directory is not None:
      directory = str(directory)
    with self.m.context(env={'CIPD_CACHE_DIR': directory}):
      yield

  @property
  def executable(self):
    return 'cipd' + ('.bat' if self.m.platform.is_win else '')

  def _run(self, name, args, step_test_data=None):
    cmd = [self.executable] + args + ['-json-output', self.m.json.output()]
    try:
      return self.m.step(name, cmd, step_test_data=step_test_data)
    except self.m.step.StepFailure:
      step_result = self.m.step.active_result
      if step_result.json.output and 'error' in step_result.json.output:
        raise self.Error(name, step_result.json.output['error'])
      else:  # pragma: no cover
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
    cmd = ['acl-check', pkg_path]
    if reader:
      cmd.append('-reader')
    if writer:
      cmd.append('-writer')
    if owner:
      cmd.append('-owner')
    step_result = self._run(
        'acl-check %s' % pkg_path,
        cmd,
        step_test_data=lambda: self.test_api.example_acl_check(pkg_path))
    return step_result.json.output['result']

  def _build(self,
             pkg_name,
             pkg_def_file_or_placeholder,
             output_package,
             pkg_vars=None,
             compression_level=None):
    cmd = [
        'pkg-build',
        '-pkg-def',
        pkg_def_file_or_placeholder,
        '-out',
        output_package,
        '-hash-algo',
        'sha256',
    ]
    cmd.extend(self._metadata_opts(pkg_vars=pkg_vars))
    cmd.extend(self._compression_level_opts(compression_level))

    step_result = self._run(
        'build %s' % pkg_name,
        cmd,
        step_test_data=lambda: self.test_api.example_build(pkg_name))
    result = step_result.json.output['result']
    return self.Pin(**result)

  def build_from_yaml(self,
                      pkg_def,
                      output_package,
                      pkg_vars=None,
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

  def build_from_pkg(self, pkg_def, output_package, compression_level=None):
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

  def build(self,
            input_dir,
            output_package,
            package_name,
            compression_level=None,
            install_mode=None,
            preserve_mtime=False,
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
    assert not install_mode or install_mode in ['copy', 'symlink']

    cmd = [
        'pkg-build',
        '-in',
        input_dir,
        '-name',
        package_name,
        '-out',
        output_package,
        '-hash-algo',
        'sha256',
    ]
    cmd.extend(self._compression_level_opts(compression_level))
    if install_mode:
      cmd.extend(['-install-mode', install_mode])
    if preserve_mtime:
      cmd.append('-preserve-mtime')
    if preserve_writable:
      cmd.append('-preserve-writable')

    step_result = self._run(
        'build %s' % self.m.path.basename(package_name),
        cmd,
        step_test_data=lambda: self.test_api.example_build(package_name))
    result = step_result.json.output['result']
    return self.Pin(**result)

  @staticmethod
  def _metadata_opts(refs=None, tags=None, metadata=None, pkg_vars=None):
    """Computes a list of -ref, -tag, -metadata and -pkg-var CLI flags."""
    refs = [] if refs is None else refs
    tags = {} if tags is None else tags
    metadata = [] if metadata is None else metadata
    pkg_vars = {} if pkg_vars is None else pkg_vars
    check_list_type('refs', refs, basestring)
    check_dict_type('tags', tags, basestring, basestring)
    check_list_type('metadata', metadata, Metadata)
    check_dict_type('pkg_vars', pkg_vars, basestring, basestring)
    ret = []
    for ref in refs:
      ret.extend(['-ref', ref])
    for tag, value in sorted(tags.items()):
      ret.extend(['-tag', '%s:%s' % (tag, value)])
    for md in sorted(metadata, key=lambda m: m._key):
      ret.extend(md._as_cli_flag())
    for var_name, value in sorted(pkg_vars.items()):
      ret.extend(['-pkg-var', '%s:%s' % (var_name, value)])
    return ret

  @staticmethod
  def _verification_timeout_opts(verification_timeout):
    if verification_timeout is None:
      return []
    check_type('verification_timeout', verification_timeout, basestring)
    if not verification_timeout.endswith(('s', 'm', 'h')):  # pragma: no cover
      raise ValueError(
          'verification_timeout must end with s, m or h, got %r' %
          verification_timeout)
    return ['-verification-timeout', verification_timeout]

  @staticmethod
  def _compression_level_opts(compression_level):
    if compression_level is None:
      return []
    check_type('compression_level', compression_level, int)
    if compression_level < 0 or compression_level > 9:  # pragma: no cover
      raise ValueError(
          'compression_level must be >=0 and <=9, got %d' % compression_level)
    return ['-compression-level', str(compression_level)]

  def register(self,
               package_name,
               package_path,
               refs=None,
               tags=None,
               metadata=None,
               verification_timeout=None):
    """Uploads and registers package instance in the package repository.

    Args:
      * package_name (str) - The name of the cipd package.
      * package_path (Path) - The path to package instance file.
      * refs (list[str]) - A list of ref names to set for the package instance.
      * tags (dict[str]basestring) - A map of tag name -> value to set for the
          package instance.
      * metadata (list[Metadata]) - A list of metadata entries to attach.
      * verification_timeout (str) - Duration string that controls the time to
        wait for backend-side package hash verification. Valid time units are
        "s", "m", "h". Default is "5m".

    Returns:
      The CIPDApi.Pin instance.
    """
    cmd = ['pkg-register', package_path]
    cmd.extend(self._metadata_opts(refs, tags, metadata))
    cmd.extend(self._verification_timeout_opts(verification_timeout))

    step_result = self._run(
        'register %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_register(package_name))
    pin = self.Pin(**step_result.json.output['result'])
    instance_link = '%s/p/%s/+/%s' % (
        CIPD_SERVER_URL,
        pin.package,
        pin.instance_id,
    )
    step_result.presentation.links[pin.package] = instance_link
    return pin

  def _create(self,
              pkg_name,
              pkg_def_file_or_placeholder,
              refs=None,
              tags=None,
              metadata=None,
              pkg_vars=None,
              compression_level=None,
              verification_timeout=None):
    cmd = [
        'create',
        '-pkg-def',
        pkg_def_file_or_placeholder,
        '-hash-algo',
        'sha256',
    ]
    cmd.extend(self._metadata_opts(refs, tags, metadata, pkg_vars))
    cmd.extend(self._compression_level_opts(compression_level))
    cmd.extend(self._verification_timeout_opts(verification_timeout))

    step_result = self._run(
        'create %s' % pkg_name,
        cmd,
        step_test_data=lambda: self.test_api.m.json.output({
            'result': self.test_api.make_pin(pkg_name),
        }))
    self.add_instance_link(step_result)
    result = step_result.json.output['result']
    return self.Pin(**result)

  def add_instance_link(self, step_result):
    result = step_result.json.output['result']
    step_result.presentation.links[result['instance_id']] = (
        'https://chrome-infra-packages.appspot.com' +
        '/p/%(package)s/+/%(instance_id)s' % result)

  def create_from_yaml(self,
                       pkg_def,
                       refs=None,
                       tags=None,
                       metadata=None,
                       pkg_vars=None,
                       compression_level=None,
                       verification_timeout=None):
    """Builds and uploads a package based on on-disk YAML package definition
    file.

    This builds and uploads the package in one step.

    Args:
      * pkg_def (Path) - The path to the yaml file.
      * refs (list[str]) - A list of ref names to set for the package instance.
      * tags (dict[str]str) - A map of tag name -> value to set for the
        package instance.
      * metadata (list[Metadata]) - A list of metadata entries to attach.
      * pkg_vars (dict[str]str) - A map of var name -> value to use for vars
        referenced in package definition file.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).
      * verification_timeout (str) - Duration string that controls the time to
        wait for backend-side package hash verification. Valid time units are
        "s", "m", "h". Default is "5m".

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, Path)
    return self._create(
        self.m.path.basename(pkg_def),
        pkg_def,
        refs, tags, metadata,
        pkg_vars,
        compression_level,
        verification_timeout)

  def create_from_pkg(self,
                      pkg_def,
                      refs=None,
                      tags=None,
                      metadata=None,
                      compression_level=None,
                      verification_timeout=None):
    """Builds and uploads a package based on a PackageDefinition object.

    This builds and uploads the package in one step.

    Args:
      * pkg_def (PackageDefinition) - The description of the package we want to
        create.
      * refs (list[str]) - A list of ref names to set for the package instance.
      * tags (dict[str]str) - A map of tag name -> value to set for the
        package instance.
      * metadata (list[Metadata]) - A list of metadata entries to attach.
      * compression_level (None|[0-9]) - Deflate compression level. If None,
        defaults to 5 (0 - disable, 1 - best speed, 9 - best compression).
      * verification_timeout (str) - Duration string that controls the time to
        wait for backend-side package hash verification. Valid time units are
        "s", "m", "h". Default is "5m".

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, PackageDefinition)
    return self._create(
        pkg_def.package_name,
        self.m.json.input(pkg_def.to_jsonish()),
        refs, tags, metadata,
        None,
        compression_level,
        verification_timeout)

  def ensure(self, root, ensure_file, name='ensure_installed'):
    """Ensures that packages are installed in a given root dir.

    Args:
      * root (Path) - Path to installation site root directory.
      * ensure_file (EnsureFile|Path) - List of packages to install.
      * name (str) - Step display name.

    Returns the map of subdirectories to CIPDApi.Pin instances.
    """
    check_type('ensure_file', ensure_file, (EnsureFile, Path))

    if isinstance(ensure_file, EnsureFile):
      step_test_data = lambda: self.test_api.example_ensure(ensure_file)
      ensure_file_path = self.m.raw_io.input(ensure_file.render())
    else:
      # ensure_file is a Path so we can't inspect its contents to construct
      # reasonable test data. So pretend we're using an empty list of packages
      # for the purpose of generating test data.
      step_test_data = lambda: self.test_api.example_ensure(self.EnsureFile())
      ensure_file_path = ensure_file

    cmd = [
        'ensure',
        '-root',
        root,
        '-ensure-file',
        ensure_file_path,
    ]
    if self.max_threads is not None:
      cmd.extend(('-max-threads', str(self.max_threads)))

    step_result = self._run(
        name,
        cmd,
        step_test_data=step_test_data,
    )
    return {
        subdir: [self.Pin(**pin) for pin in pins]
        for subdir, pins in iteritems(step_result.json.output['result'])
    }

  def ensure_file_resolve(self, ensure_file, name='cipd ensure-file-resolve'):
    """Resolves versions of all packages for all verified platforms in an
    ensure file.

    Args:
      * ensure_file (EnsureFile|Path) - Ensure file to resolve.
    """
    check_type('ensure_file', ensure_file, (EnsureFile, Path))

    if isinstance(ensure_file, EnsureFile):
      step_test_data = lambda: self.test_api.example_ensure_file_resolve(
          ensure_file)
      ensure_file_path = self.m.raw_io.input(ensure_file.render())
    else:
      step_test_data = lambda: self.test_api.example_ensure_file_resolve(
          self.EnsureFile())
      ensure_file_path = ensure_file

    cmd = [
        'ensure-file-resolve',
        '-ensure-file',
        ensure_file_path,
    ]

    return self._run(
        name,
        cmd,
        step_test_data=step_test_data,
    )

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
        'set-tag',
        package_name,
        '-version',
        version,
    ]
    cmd.extend(self._metadata_opts(tags=tags))

    step_result = self._run(
        'cipd set-tag %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_set_tag(
            package_name, version))
    result = step_result.json.output['result']
    return self.Pin(**result[0]['pin'])

  def set_metadata(self, package_name, version, metadata):
    """Attaches metadata to a package instance.

    Args:
      * package_name (str) - The name of the cipd package.
      * version (str) - The package version to attach metadata to.
      * metadata (list[Metadata]) - A list of metadata entries to attach.

    Returns the CIPDApi.Pin instance.
    """
    cmd = [
        'set-metadata',
        package_name,
        '-version',
        version,
    ]
    cmd.extend(self._metadata_opts(metadata=metadata))

    step_result = self._run(
        'cipd set-metadata %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_set_metadata(
            package_name, version))
    result = step_result.json.output['result']
    return self.Pin(**result[0]['pin'])

  def set_ref(self, package_name, version, refs):
    """Moves a ref to point to a given version.

    Args:
      * package_name (str) - The name of the cipd package.
      * version (str) - The package version to point the ref to.
      * refs (list[str]) - A list of ref names to set for the package instance.

    Returns the CIPDApi.Pin instance.
    """
    cmd = [
        'set-ref',
        package_name,
        '-version',
        version,
    ]
    cmd.extend(self._metadata_opts(refs=refs))

    step_result = self._run(
        'cipd set-ref %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_set_ref(
            package_name, version))
    result = step_result.json.output['result']
    return self.Pin(**result[''][0]['pin'])

  def search(self, package_name, tag, test_instances=None):
    """Searches for package instances by tag, optionally constrained by package
    name.

    Args:
      * package_name (str) - The name of the cipd package.
      * tag (str) - The cipd package tag.
      * test_instances (None|int|List[str]) - Default test data for this step:
        * None - Search returns a single default pin.
        * int - Search generates `test_instances` number of testing IDs
          `instance_id_%d` and returns pins for those.
        * List[str] - Returns pins for the given testing IDs.

    Returns the list of CIPDApi.Pin instances.
    """
    assert ':' in tag, 'tag must be in a form "k:v"'

    cmd = [
        'search',
        package_name,
        '-tag',
        tag,
    ]

    step_result = self._run(
        'cipd search %s %s' % (package_name, tag),
        cmd,
        step_test_data=lambda: self.test_api.example_search(
            package_name, test_instances)
    )
    return [self.Pin(**pin) for pin in step_result.json.output['result'] or []]

  def describe(self,
               package_name,
               version,
               test_data_refs=None,
               test_data_tags=None):
    """Returns information about a package instance given its version:
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
            package_name,
            version,
            test_data_refs=test_data_refs,
            test_data_tags=test_data_tags))
    result = step_result.json.output['result']
    return self.Description(
        pin=self.Pin(**result['pin']),
        registered_by=result['registered_by'],
        registered_ts=result['registered_ts'],
        refs=[self.Ref(**ref) for ref in result.get('refs', ())],
        tags=[self.Tag(**tag) for tag in result.get('tags', ())],
    )

  def instances(self,
                package_name,
                limit=None):
    """Lists instances of a package, most recently uploaded first.

    Args:
      * package_name (str) - The name of the cipd package.
      * limit (None|int) - The number of instances to return. 0 for all.
        If None, default value of 'cipd' binary will be used (20).

    Returns the list of CIPDApi.Instance instance.
    """
    check_type('package_name', package_name, basestring)
    check_type('limit', limit, (type(None), int))
    cmd = [
        'instances',
        package_name,
    ]
    if limit is not None:
      cmd += ['-limit', limit]

    step_result = self._run(
        'cipd instances %s' % package_name, cmd,
        step_test_data=lambda: self.test_api.example_instances(
            package_name,
            limit=limit))
    result = step_result.json.output['result'] or {}
    instances = []
    for instance in result.get('instances', []):
      instances.append(self.Instance(
        pin=self.Pin(**instance['pin']),
        registered_by=instance['registered_by'],
        registered_ts=instance['registered_ts'],
        refs=instance.get('refs'),
      ))
    return instances

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
    check_type('package_name', package_name, basestring)
    check_type('version', version, basestring)

    step_result = self._run(
        'cipd pkg-fetch %s' % package_name,
        ['pkg-fetch', package_name, '-version', version, '-out', destination],
        step_test_data=lambda: self.test_api.example_pkg_fetch(
            package_name, version))
    ret = self.Pin(**step_result.json.output['result'])
    step_result.presentation.step_text = '%s %s' % (ret.package,
                                                    ret.instance_id)
    return ret

  def pkg_deploy(self, root, package_file):
    """Deploys the specified package to root.

    ADVANCED METHOD: You shouldn't need this unless you're doing advanced
    things with CIPD. Typically you should use the `ensure` method here to
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
            'pkg/name/of/' + package_file.pieces[-1], 'version/of/' +
            package_file.pieces[-1]))
    return self.Pin(**step_result.json.output['result'])

  def ensure_tool(self,
                  package: str,
                  version: str,
                  executable_path: Optional[str] = None):
    """Downloads an executable from CIPD.

    Given a package named "name/of/some_exe/${platform}" and version
    "someversion", this will install the package at the directory
    "[START_DIR]/cipd_tool/name/of/some_exe/someversion". It will then return
    the absolute path to the executable within that directory.

    This operation is idempotent, and will only run steps to download the
    package if it hasn't already been installed in the same build.

    Args:
      * package (str) - The full name of the CIPD package.
      * version (str) - The version of the package to download.
      * executable_path (str|None) - The path within the package of the desired
        executable. Defaults to the basename of the package (the final
        non-variable component of the package name). Must use forward-slashes,
        even on Windows.

    Returns a Path to the executable.

    Future-safe; Multiple concurrent calls for the same (package, version) will
    block on a single ensure step.
    """

    check_type("package", package, str)
    check_type("version", version, str)
    check_type("executable_path", executable_path, (str, type(None)))

    cache_key = (package, version)

    package_parts = [p for p in package.split('/') if '${' not in p]
    package_dir = self.m.path['start_dir'].join('cipd_tool', *package_parts)
    # Hashing the version is the easiest way to produce a string with no special
    # characters e.g. removing colons which don't work on Windows.
    package_dir = package_dir.join(
        hashlib.sha256(version.encode('utf-8')).hexdigest())
    basename = package_parts[-1]

    if cache_key not in self._installed_tool_package_futures:
      name = 'install %s' % ('/'.join(package_parts),)

      def _install_package_thread():
        with self.m.step.nest(name):
          with self.m.context(infra_steps=True):
            self.m.file.ensure_directory('ensure package directory',
                                         package_dir)
            self.ensure(
                package_dir,
                self.EnsureFile().add_package(package, version))

      self._installed_tool_package_futures[cache_key] = self.m.futures.spawn(
          _install_package_thread, __name='recipe_engine/cipd: '+name)

    self._installed_tool_package_futures[cache_key].result()

    if executable_path is None:
      executable_path = basename

    return package_dir.join(*executable_path.split('/'))
