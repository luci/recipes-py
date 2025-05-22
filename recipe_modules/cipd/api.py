# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with CIPD.

Depends on 'cipd' binary available in PATH:
https://godoc.org/go.chromium.org/luci/cipd/client/cmd/cipd
"""

from __future__ import annotations

from collections import defaultdict, namedtuple
from collections.abc import Mapping, Sequence
import contextlib
import hashlib
from typing import Iterator, Literal

from past.builtins import basestring

from recipe_engine import recipe_api, recipe_test_api, step_data, util
from recipe_engine.config_types import Path
from recipe_engine.recipe_utils import check_type, check_list_type, check_dict_type

CIPD_SERVER_URL = 'https://chrome-infra-packages.appspot.com'

CompressionLevel = Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
InstallMode = Literal['copy', 'symlink']


class PackageDefinition:
  DIR = namedtuple('DIR', ['path', 'exclusions'])

  def __init__(self,
               package_name: str,
               package_root: Path,
               install_mode: InstallMode | None = None,
               preserve_mtime: bool = False,
               preserve_writable: bool = False):
    """Build a new PackageDefinition.

    Args:
      * package_name - the name of the CIPD package
      * package_root - the path on the current filesystem that all files
        will be relative to. e.g. if your root is /.../foo, and you add the
        file /.../foo/bar/baz.json, the final cipd package will contain
        'bar/baz.json'.
      * install_mode - the mechanism that the cipd client should use when
        installing this package. If None, defaults to the platform default
        ('copy' on windows, 'symlink' on everything else).
      * preserve_mtime - Preserve file's modification time.
      * preserve_writable - Preserve file's writable permission bit.
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

    self.dirs: list[DIR] = []
    self.files: list[Path] = []
    self.version_file: str | None = None

  def _rel_path(self, path: Path) -> str:
    """Returns a forward-slash-delimited version of `path` which is relative to
    the package root. Will raise ValueError if path is not inside the root."""
    if path == self.package_root:
      return '.'
    if not self.package_root in path.parents:
      raise ValueError(
          'path %r is not the package root %r and not a child thereof' %
          (path, self.package_root))
    # we know that root has the same base and some prefix of path
    return '/'.join(path.pieces[len(self.package_root.pieces):])

  def add_dir(self, dir_path: Path, exclusions: list[str] | None = None):
    """Recursively add a directory to the package.

    Args:
      * dir_path - A path on the current filesystem under the
        package_root to a directory which should be recursively included.
      * exclusions - A list of regexps to exclude when scanning the
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

  def add_file(self, file_path: Path) -> None:
    """Add a single file to the package.

    Args:
      * file_path - A path on the current filesystem to the file you
        wish to include.

    Raises:
      * ValueError - file_path is not a subdirectory of the package root.
    """
    check_type('file_path', file_path, Path)
    self.files.append(self._rel_path(file_path))

  def add_version_file(self, ver_file_rel: str) -> None:
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
      * ver_file_rel - A path string relative to the installation root.
        Should be specified in posix style (forward/slashes).
    """
    check_type('ver_file_rel', ver_file_rel, basestring)
    if self.version_file is not None:
      raise ValueError('add_version_file() may only be used once.')
    self.version_file = ver_file_rel

  def to_jsonish(self) -> dict:
    """Returns a JSON representation of this PackageDefinition."""
    output = {
        'package': self.package_name,
        'root': str(self.package_root),
        'install_mode': self.install_mode or '',
        'data': (
            [{'file': str(f)} for f in self.files]
            + [{'dir': str(d.path), 'exclude': d.exclusions} for d in self.dirs]
            + ([{'version_file': self.version_file}] if self.version_file else [])
        )
    }
    if self.preserve_mtime:
      output['preserve_mtime'] = self.preserve_mtime
    if self.preserve_writable:
      output['preserve_writable'] = self.preserve_writable
    return output


class EnsureFile:
  Package = namedtuple('Package', ['name', 'version'])

  def __init__(self):
    self.packages: dict[Path, list[Package]] = defaultdict(list)

  def add_package(self, name: str, version: str, subdir: str = '') -> EnsureFile:
    """Add a package to the ensure file.

    Args:
      * name - Name of the package, must be for right platform.
      * version - Could be either instance_id, or ref, or unique tag.
      * subdir - Subdirectory of root dir for the package.
    """
    self.packages[subdir].append(self.Package(name, version))
    return self

  def render(self) -> str:
    """Renders the ensure file as textual representation."""
    package_list = []
    for subdir in sorted(self.packages):
      if subdir:
        package_list.append('@Subdir %s' % subdir)
      for package in self.packages[subdir]:
        package_list.append('%s %s' % (package.name, package.version))
    return '\n'.join(package_list)


class Metadata:
  def __init__(
      self,
      key: str,
      value: str | None = None,
      value_from_file: Path | None = None,
      content_type: str | None = None,
  ):
    """Constructs a metadata entry to attach to a package instance.

    Each entry has a key (doesn't have to be unique), a value (supplied either
    directly as a string or read from a file), and a content type. The content
    type can be omitted, the CIPD client will try to guess it in this case.

    Args:
      * key - the metadata key.
      * value - the literal metadata value. Can't be used together
        with 'value_from_file'.
      * value_from_file - the path to read the value from. Can't be
        used together with 'value'.
      * content-type - a content type of the metadata value
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

  def _as_cli_flag(self) -> list[str]:
    key = self._key
    if self._content_type:
      key += '(%s)' % self._content_type
    if self._value_from_file:
      return ['-metadata-from-file', '%s:%s' % (key, self._value_from_file)]
    return ['-metadata', '%s:%s' % (key, self._value)]

  @property
  def key(self) -> str:
    return self._key


class UnrecognizedArchitecture(ValueError):
  pass


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
  UnrecognizedArchitecture = UnrecognizedArchitecture

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

  CompressionLevel = CompressionLevel
  InstallMode = InstallMode

  class Error(recipe_api.InfraFailure):

    def __init__(self, step_name, message):
      reason = 'CIPD(%r) failed with: %s' % (step_name, message)
      super().__init__(reason)

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self.max_threads = 0  # 0 means use system CPU count.
    # A mapping from (package, version) to Future for packages installed
    # via `ensure_tool()`. The Future has no returned value and just used to
    # synchronize 'ensure' actions.
    self._installed_tool_package_futures = {}

  @contextlib.contextmanager
  def cache_dir(self, directory: Path | None) -> Iterator[None]:
    """Sets the cache dir to use with CIPD by setting the $CIPD_CACHE_DIR
    environment variable.

    If directory is "None", will use no cache directory.
    """
    if directory is not None:
      directory = str(directory)
    with self.m.context(env={'CIPD_CACHE_DIR': directory}):
      yield

  @property
  def executable(self) -> str:
    return 'cipd' + ('.bat' if self.m.platform.is_win else '')

  def _run(
      self,
      name: str,
      args: Sequence[str | Path | util.Placeholder],
      step_test_data: Callable[[], recipe_test_api.StepTestData] | None = None,
  ) -> step_data.StepData:
    cmd: list[str | Path | util.Placeholder] = (
        [self.executable] + args + ['-json-output', self.m.json.output()]
    )
    try:
      return self.m.step(
          name, cmd, step_test_data=step_test_data, infra_step=True)
    except self.m.step.StepFailure:
      step_result = self.m.step.active_result
      if step_result.json.output and 'error' in step_result.json.output:
        raise self.Error(name, step_result.json.output['error'])
      else:  # pragma: no cover
        raise

  def acl_check(
      self,
      pkg_path: str,
      reader: bool = True,
      writer: bool = False,
      owner: bool = False,
  ) -> bool:
    """Checks whether the caller has a given roles in a package.

    Args:
      * pkg_path - The package subpath.
      * reader - Check for READER role.
      * writer - Check for WRITER role.
      * owner - Check for OWNER role.

    Returns True if the caller has given roles, False otherwise.
    """
    cmd: list[str] = ['acl-check', pkg_path]
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

  def _build(
      self,
      pkg_name: str,
      pkg_def_file_or_placeholder,
      output_package: str,
      pkg_vars=None,
      compression_level: CompressionLevel | None = None,
  ) -> Pin:
    cmd: list[str | Path | util.Placeholder] = [
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

  def build_from_yaml(
      self,
      pkg_def: Path,
      output_package: Path,
      pkg_vars: dict[str, str] = None,
      compression_level: CompressionLevel | None = None,
  ) -> Pin:
    """Builds a package based on on-disk YAML package definition file.

    Args:
      * pkg_def - The path to the yaml file.
      * output_package - The file to write the package to.
      * pkg_vars - A map of var name -> value to use for vars
        referenced in package definition file.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).

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

  def build_from_pkg(
      self,
      pkg_def: PackageDefinition,
      output_package: Path,
      compression_level: CompressionLevel | None = None,
  ) -> Pin:
    """Builds a package based on a PackageDefinition object.

    Args:
      * pkg_def - The description of the package we want to create.
      * output_package - The file to write the package to.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).

    Returns the CIPDApi.Pin instance.
    """
    check_type('pkg_def', pkg_def, PackageDefinition)
    return self._build(
        pkg_def.package_name,
        self.m.json.input(pkg_def.to_jsonish()),
        output_package,
        compression_level=compression_level,
    )

  def build(
      self,
      input_dir: Path,
      output_package: Path,
      package_name: str,
      compression_level: CompressionLevel | None = None,
      install_mode: InstallMode | None = None,
      preserve_mtime: bool = False,
      preserve_writable: bool = False,
  ) -> Pin:
    """Builds, but does not upload, a cipd package from a directory.

    Args:
      * input_dir - The directory to build the package from.
      * output_package - The file to write the package to.
      * package_name - The name of the cipd package as it would appear
        when uploaded to the cipd package server.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).
      * install_mode - The mechanism that the cipd client should use when
        installing this package. If None, defaults to the platform default
        ('copy' on windows, 'symlink' on everything else).
      * preserve_mtime - Preserve file's modification time.
      * preserve_writable - Preserve file's writable permission bit.

    Returns the CIPDApi.Pin instance.
    """
    assert not install_mode or install_mode in ['copy', 'symlink']

    cmd: list[str | Path | util.Placeholder] = [
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

  def _metadata_opts(
      self,
      refs: Sequence[str] | None = None,
      tags: Mapping[str, str] | None = None,
      metadata: Sequence[Metadata] | None = None,
      pkg_vars: Mapping[str, str] | None = None,
      add_build_id_metadata: bool = False,
  ) -> list[str]:
    """Computes a list of -ref, -tag, -metadata and -pkg-var CLI flags."""
    refs = [] if refs is None else refs
    tags = {} if tags is None else tags
    metadata = [] if metadata is None else metadata
    pkg_vars = {} if pkg_vars is None else pkg_vars
    check_list_type('refs', refs, basestring)
    check_dict_type('tags', tags, basestring, basestring)
    check_list_type('metadata', metadata, Metadata)
    check_dict_type('pkg_vars', pkg_vars, basestring, basestring)

    if add_build_id_metadata:
      build_id = str(self.m.buildbucket.build.id)
      if all(x.key != 'build_id' for x in metadata):
        metadata.append(Metadata('build_id', build_id))

    ret: list[str] = []
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
  def _verification_timeout_opts(verification_timeout: str) -> list[str]:
    if verification_timeout is None:
      return []
    check_type('verification_timeout', verification_timeout, basestring)
    if not verification_timeout.endswith(('s', 'm', 'h')):  # pragma: no cover
      raise ValueError(
          'verification_timeout must end with s, m or h, got %r' %
          verification_timeout)
    return ['-verification-timeout', verification_timeout]

  @staticmethod
  def _compression_level_opts(
      compression_level: CompressionLevel | None,
  ) -> list[str]:
    if compression_level is None:
      return []
    check_type('compression_level', compression_level, int)
    if compression_level < 0 or compression_level > 9:  # pragma: no cover
      raise ValueError(
          'compression_level must be >=0 and <=9, got %d' % compression_level)
    return ['-compression-level', str(compression_level)]

  def register(
      self,
      package_name: str,
      package_path: Path,
      refs: Sequence[str] | None = None,
      tags: Mapping[str, str] | None = None,
      metadata: Sequence[Metadata] = None,
      verification_timeout: str | None = None,
  ) -> Pin:
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
    cmd: list[str | Path | util.Placeholder] = ['pkg-register', package_path]
    cmd.extend(self._metadata_opts(refs, tags, metadata, add_build_id_metadata=True))
    cmd.extend(self._verification_timeout_opts(verification_timeout))

    step_result = self._run(
        'register %s' % package_name,
        cmd,
        step_test_data=lambda: self.test_api.example_register(package_name))
    pin = self.Pin(**step_result.json.output['result'])
    instance_link = self.make_link(pin.package, pin.instance_id)
    step_result.presentation.links[pin.package] = instance_link
    return pin

  def _create(
      self,
      pkg_name: str,
      pkg_def_file_or_placeholder: Path | util.Placeholder,
      refs: Sequence[str] | None = None,
      tags: Mapping[str, str] | None = None,
      metadata: Sequence[Metadata] = None,
      pkg_vars: Mapping[str, str] = None,
      compression_level: CompressionLevel | None = None,
      verification_timeout: str | None = None,
  ) -> Pin:
    cmd: list[str | Path | util.Placeholder] = [
        'create',
        '-pkg-def',
        pkg_def_file_or_placeholder,
        '-hash-algo',
        'sha256',
    ]
    cmd.extend(self._metadata_opts(refs, tags, metadata, pkg_vars,
                                   add_build_id_metadata=True))
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

  def make_link(self, package: str, version: str) -> str:
    return f'{CIPD_SERVER_URL}/p/{package}/+/{version}'

  def add_instance_link(self, step_result: step_data.StepData) -> None:
    result = step_result.json.output['result']
    step_result.presentation.links[result['instance_id']] = self.make_link(
        package=result['package'], version=result['instance_id'])

  def create_from_yaml(
      self,
      pkg_def: Path,
      refs: Sequence[str] | None = None,
      tags: Mapping[str, str] | None = None,
      metadata: Sequence[Metadata] | None = None,
      pkg_vars: Mapping[str, str] | None = None,
      compression_level: CompressionLevel | None = None,
      verification_timeout: str | None = None,
  ) -> Pin:
    """Builds and uploads a package based on on-disk YAML package definition
    file.

    This builds and uploads the package in one step.

    Args:
      * pkg_def - The path to the yaml file.
      * refs - A list of ref names to set for the package instance.
      * tags - A map of tag name -> value to set for the package instance.
      * metadata - A list of metadata entries to attach.
      * pkg_vars - A map of var name -> value to use for vars
        referenced in package definition file.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).
      * verification_timeout - Duration string that controls the time to
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

  def create_from_pkg(
      self,
      pkg_def: PackageDefinition,
      refs: Sequence[str] | None = None,
      tags: Mapping[str, str] | None = None,
      metadata: Sequence[Metadata] | None = None,
      compression_level: CompressionLevel | None = None,
      verification_timeout: str | None = None,
  ) -> Pin:
    """Builds and uploads a package based on a PackageDefinition object.

    This builds and uploads the package in one step.

    Args:
      * pkg_def - The description of the package we want to create.
      * refs - A list of ref names to set for the package instance.
      * tags - A map of tag name -> value to set for the package instance.
      * metadata - A list of metadata entries to attach.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).
      * verification_timeout - Duration string that controls the time to
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

  def ensure(
      self,
      root: Path,
      ensure_file: EnsureFile | Path,
      name: str = 'ensure_installed',
  ) -> Pin:
    """Ensures that packages are installed in a given root dir.

    Args:
      * root - Path to installation site root directory.
      * ensure_file - List of packages to install.
      * name - Step display name.

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

    cmd: list[str | Path | util.Placeholder] = [
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
        for subdir, pins in step_result.json.output['result'].items()
    }

  def ensure_file_resolve(
      self,
      ensure_file: EnsureFile | Path,
      name: str = 'cipd ensure-file-resolve',
  ) -> step_data.StepData:
    """Resolves versions of all packages for all verified platforms in an
    ensure file.

    Args:
      * ensure_file - Ensure file to resolve.
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

    cmd: list[str | Path | util.Placeholder] = [
        'ensure-file-resolve',
        '-ensure-file',
        ensure_file_path,
    ]

    return self._run(
        name,
        cmd,
        step_test_data=step_test_data,
    )

  def set_tag(
      self,
      package_name: str,
      version: str,
      tags: dict[str, str],
  ) -> Pin:
    """Tags package of a specific version.

    Args:
      * package_name - The name of the cipd package.
      * version - The package version to resolve. Could also be itself a
        tag or ref.
      * tags - A map of tag name -> value to set for the package instance.

    Returns the CIPDApi.Pin instance.
    """
    cmd: list[str | Path | util.Placeholder] = [
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

  def set_metadata(
      self,
      package_name: str,
      version: str,
      metadata: list[Metadata],
  ) -> Pin:
    """Attaches metadata to a package instance.

    Args:
      * package_name - The name of the cipd package.
      * version - The package version to attach metadata to.
      * metadata - A list of metadata entries to attach.

    Returns the CIPDApi.Pin instance.
    """
    cmd: list[str | Path | util.Placeholder] = [
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

  def set_ref(
      self,
      package_name: str,
      version: str,
      refs: list[str],
  ) -> Pin:
    """Moves a ref to point to a given version.

    Args:
      * package_name - The name of the cipd package.
      * version - The package version to point the ref to.
      * refs - A list of ref names to set for the package instance.

    Returns the CIPDApi.Pin instance.
    """
    cmd: list[str | Path | util.Placeholder] = [
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

  def search(
      self,
      package_name: str,
      tag: str,
      test_instances: list[str] | int | None = None,
  ) -> list[Pin]:
    """Searches for package instances by tag, optionally constrained by package
    name.

    Args:
      * package_name - The name of the cipd package.
      * tag - The cipd package tag.
      * test_instances - Default test data for this step:
        * None - Search returns a single default pin.
        * int - Search generates `test_instances` number of testing IDs
          `instance_id_%d` and returns pins for those.
        * List[str] - Returns pins for the given testing IDs.

    Returns the list of CIPDApi.Pin instances.
    """
    assert ':' in tag, 'tag must be in a form "k:v"'

    cmd: list[str | Path | util.Placeholder] = [
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
               package_name: str,
               version: str,
               test_data_refs: Sequence[str] | None = None,
               test_data_tags: Sequence[str] | None = None) -> Description:
    """Returns information about a package instance given its version:
    who uploaded the instance and when and a list of attached tags.

    Args:
      * package_name - The name of the cipd package.
      * version - The package version to point the ref to.
      * test_data_refs - The list of refs for this call to return
        by default when in test mode.
      * test_data_tags - The list of tags (in 'name:val' form) for
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

  def instances(
      self,
      package_name: str,
      limit: int | None = None,
  ) -> list[Instance]:
    """Lists instances of a package, most recently uploaded first.

    Args:
      * package_name - The name of the cipd package.
      * limit - The number of instances to return. 0 for all.
        If None, default value of 'cipd' binary will be used (20).

    Returns the list of CIPDApi.Instance instance.
    """
    check_type('package_name', package_name, basestring)
    check_type('limit', limit, (type(None), int))
    cmd: list[str | Path | util.Placeholder] = [
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
    instances: list[Instance] = []
    for instance in result.get('instances', []):
      instances.append(self.Instance(
        pin=self.Pin(**instance['pin']),
        registered_by=instance['registered_by'],
        registered_ts=instance['registered_ts'],
        refs=instance.get('refs'),
      ))
    return instances

  def pkg_fetch(
      self,
      destination: Path,
      package_name: str,
      version: str,
  ) -> Pin:
    """Downloads the specified package to destination.

    ADVANCED METHOD: You shouldn't need this unless you're doing advanced things
    with CIPD. Typically you should use the `ensure` method here to
    fetch+install packages to the disk.

    Args:
      * destination - Path to a file location which will be (over)written
        with the package file contents.
      * package_name - The package name (or pattern with e.g. ${platform})
      * version - The CIPD version to fetch

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

  def pkg_deploy(self, root: Path, package_file: Path) -> Pin:
    """Deploys the specified package to root.

    ADVANCED METHOD: You shouldn't need this unless you're doing advanced
    things with CIPD. Typically you should use the `ensure` method here to
    fetch+install packages to the disk.

    Args:
      * package_file - Path to a package file to install.
      * root - Path to a CIPD root.

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
                  executable_path: str | None = None) -> Path:
    """Downloads an executable from CIPD.

    Given a package named "name/of/some_exe/${platform}" and version
    "someversion", this will install the package at the directory
    "[START_DIR]/cipd_tool/name/of/some_exe/someversion". It will then return
    the absolute path to the executable within that directory.

    This operation is idempotent, and will only run steps to download the
    package if it hasn't already been installed in the same build.

    Args:
      * package - The full name of the CIPD package.
      * version - The version of the package to download.
      * executable_path - The path within the package of the desired
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
    package_dir = self.m.path.start_dir.joinpath('cipd_tool', *package_parts)
    # Hashing the version is the easiest way to produce a string with no special
    # characters e.g. removing colons which don't work on Windows.
    package_dir = package_dir.joinpath(
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

    return package_dir / executable_path

  def _full_arch(self, arch: str, bits: int | str) -> str:
    bits = int(bits)
    assert bits in (32, 64)

    if arch == 'intel':
      return 'amd64' if bits == 64 else '386'

    if arch == 'arm':
      return 'arm64' if bits == 64 else 'armv6l'

    raise UnrecognizedArchitecture(arch)  # pragma: no cover

  @property
  def platform(self) -> str:
    """Returns the CIPD platform string, equivalent to '${platform}'."""

    os_part = self.m.platform.name.replace('win', 'windows')
    arch_part = self._full_arch(self.m.platform.arch, self.m.platform.bits)
    return f'{os_part}-{arch_part}'
