# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""File manipulation (read/write/delete/glob) methods."""

import fnmatch
import hashlib
import os
from typing import Any, Callable, Literal, Sequence, TypeVar

import google.protobuf
from recipe_engine import config_types, recipe_api, recipe_test_api, step_data


class SymlinkTree:
  """A representation of a tree of symlinks."""

  def __init__(
      self,
      root: config_types.Path,
      api: recipe_api.RecipeApi,
      symlink_resource,
  ) -> None:
    """See FileApi.symlink_tree for the public constructor."""
    assert root and isinstance(root, config_types.Path)
    self._root = root
    self._api = api
    self._resource = symlink_resource
    #  Maps target to a list of linknames.
    self._link_map: dict[config_types.Path, list[config_types.Path]] = {}
    #  Maps a linkname to its target.
    self._reverse_map: dict[config_types.Path, config_types.Path] = {}

  @property
  def root(self) -> config_types.Path:
    """The root (Path) of the symlink tree."""
    return self._root

  def register_link(
      self,
      target: config_types.Path,
      linkname: config_types.Path,
  ) -> None:
    """Registers a pair of paths to symlink.

    Args:
      * target: The file/directory to which the symlink will point.
      * linkname: The location of the symlink. Must be a child of the
          SymlinkTree's `root`. It is an error to register two links with the
          same linkname.
    """
    assert (isinstance(target, config_types.Path) and
            isinstance(linkname, config_types.Path))
    if linkname in self._link_map.get(target, ()):
      return
    else:
      assert linkname not in self._reverse_map, (
          '%s is already linked to %s' %
          (linkname, self._reverse_map[linkname]))

    assert self.root in linkname.parents, (
        '%s is not within the root directory %s' % (linkname, self.root))
    self._link_map.setdefault(target, []).append(linkname)
    self._reverse_map[linkname] = target

  def create_links(self, name: str) -> step_data.StepData:
    """Creates all registered symlinks on disk.

    Args:
      * name: The name of the step.
    """
    for target, linknames in self._link_map.items():
      for linkname in linknames:
        self._api.path.mock_copy_paths(target, linkname)
    args = [
        'python3',
        '-u',
        self._resource,
        '--link-json',
        self._api.json.input({
            str(target): linkname
            for target, linkname in self._link_map.items()
        }),
    ]
    return self._api.step(name, args, infra_step=True)


ProtoCodec = Literal['BINARY', 'JSONPB', 'TEXTPB']

# TODO(iannucci): Introduce the concept of a 'native step' and implement these
# directly in the current python interpreter without the need for a subprocess
# invocation.


class FileApi(recipe_api.RecipeApi):

  ProtoCodec = ProtoCodec

  class Error(recipe_api.StepFailure):
    """Error is a StepFailure, except that it also contains an errno field
    indicating the errno name (i.e. 'EEXIST') of the underlying error.
    """

    def __init__(
        self,
        step_name: str,
        errno_name: str,
        message: str,
    ) -> None:
      reason = 'Step(%r) failed %r with: %s' % (step_name, errno_name, message)
      super().__init__(reason)
      self.errno_name = errno_name

  def _assert_absolute_path_or_placeholder(
      self,
      path_or_placeholder: config_types.Path | str | recipe_api.Placeholder,
  ) -> None:
    if isinstance(path_or_placeholder, recipe_api.Placeholder):
      # We assume that all Placeholder classes will render to an absolute path,
      # as this is part of their api contract.
      return
    return self.m.path.assert_absolute(path_or_placeholder)

  def _run(
      self,
      name: str,
      args: Sequence[config_types.Path | str | recipe_api.Placeholder],
      step_test_data: Callable[[], recipe_test_api.StepTestData] | None = None,
      stdout: config_types.Path | recipe_api.Placeholder | None = None,
  ) -> step_data.StepData:
    if not step_test_data:
      step_test_data = self.test_api.errno
    args = [
      'vpython3', '-u',
      self.resource('fileutil.py'),
      '--json-output', self.m.json.output(add_json_log=False),
    ] + args
    result = self.m.step(
        name, args,
        step_test_data=step_test_data,
        stdout=stdout,
        infra_step=True)
    j = result.json.output
    if not j['ok']:
      result.presentation.status = self.m.step.FAILURE
      result.presentation.step_text = j['message']
      # pylint thinks this isn't a standard exception... silly pylint.
      # pylint: disable=nonstandard-exception
      raise self.Error(name, j['errno_name'], j['message'])
    return result

  def copy(
      self,
      name: str,
      source: config_types.Path | str | recipe_api.Placeholder,
      dest: config_types.Path | str | recipe_api.Placeholder,
  ) -> step_data.StepData:
    """Copies a file (including mode bits) from source to destination on the
    local filesystem.

    Behaves identically to shutil.copy.

    Args:
      * name: The name of the step.
      * source: The path to the file you want to copy.
      * dest: The path to the destination file name. If this path exists and is
        a directory, the basename of `source` will be appended to derive a path
        to a destination file.

    Raises: file.Error
    """
    self._assert_absolute_path_or_placeholder(source)
    self._assert_absolute_path_or_placeholder(dest)
    result = self._run(name, ['copy', source, dest])
    self.m.path.mock_copy_paths(source, dest)
    return result

  def copytree(
      self,
      name: str,
      source: config_types.Path | str,
      dest: config_types.Path | str,
      symlinks: bool = False,
      hardlink: bool = False,
      allow_override: bool = False,
  ) -> step_data.StepData:
    """Recursively copies a directory tree.

    Behaves identically to shutil.copytree.
    `dest` must not exist.

    Args:
      * name (str): The name of the step.
      * source (Path): The path of the directory to copy.
      * dest (Path): The place where you want the recursive copy to show up.
        This must not already exist.
      * symlinks (bool): Preserve symlinks. No effect on Windows.
      * hardlink (bool): Create hardlinks using os.link(), instead of copying
        the files.
      * allow_override (bool): If True, existing files in `dest` will be
        overridden. If False or not specified, the copy will be stopped with
        raising `file.Error` exception if the file exists in `dest`.

    Raises: file.Error
    """
    self.m.path.assert_absolute(source)
    self.m.path.assert_absolute(dest)
    args = []
    if symlinks:
      args += ['--symlinks']
    if hardlink:
      args += ['--hardlink']
    if allow_override:
      args += ['--allow-override']
    result = self._run(name, ['copytree'] + args + [source, dest])
    self.m.path.mock_copy_paths(source, dest)
    return result

  def chmod(
      self,
      name: str,
      path: config_types.Path | str,
      mode: str,
      recursive: bool = False,
  ) -> step_data.StepData:
    """Set the access mode for a file or directory.

    Args:
      * name: The name of the step.
      * path: The path of the file or directory.
      * mode: The access mode in octal.
      * recursive: Whether to run chmod recursively.

    Raises: file.Error
    """
    self.m.path.assert_absolute(path)
    assert isinstance(mode, str)
    cmd = ['chmod', path, '--mode', mode]
    if recursive:
      cmd.append('--recursive')
    return self._run(name, cmd)

  def move(
      self,
      name: str,
      source: config_types.Path | str,
      dest: config_types.Path | str,
  ) -> step_data.StepData:
    """Moves a file or directory.

    Behaves identically to shutil.move.

    Args:
      * name (str): The name of the step.
      * source (Path): The path of the item to move.
      * dest (Path): The new name of the item.

    Raises: file.Error
    """
    self.m.path.assert_absolute(source)
    self.m.path.assert_absolute(dest)
    result = self._run(name, ['move', source, dest])
    self.m.path.mock_copy_paths(source, dest)
    self.m.path.mock_remove_paths(source)
    return result

  def file_hash(
      self,
      file_path: config_types.Path | str,
      test_data: str = '',
  ) -> str:
    """Computes hash of contents of a single file.

    Args:
      * file_path: Path of file to compute hash.
      * test_data: Some default data for this step to return when running under
        simulation. If no test data is provided, we compute test_data as sha256
        of path passed.

    Returns:
      Hex encoded hash of file content.

    Raises:
      file.Error and ValueError if passed paths input is not str or Path.
    """
    if not isinstance(file_path, (str, config_types.Path)):  # pragma: no cover
      raise ValueError('Expected str or path object, got %r' % type(path))
    self.m.path.assert_absolute(file_path)

    if not test_data:
      test_data = hashlib.sha256(str(file_path).encode('utf-8')).hexdigest()
    result = self._run(
        'Compute file hash', ['file_hash', file_path],
        step_test_data=lambda: self.test_api.file_hash(test_data),
        stdout=self.m.raw_io.output_text())
    sha = result.stdout.strip()
    result.presentation.step_text = 'Hash calculated: %s' % sha
    return sha

  def compute_hash(
      self,
      name: str,
      paths: Sequence[config_types.Path | str],
      base_path: config_types.Path | str,
      test_data: str = '',
  ) -> str:
    """Computes hash of contents of a directory/file.

    This function will compute hash by including following info of a file:
      * str(len(path))  // path is relative to base_path
      * path            // path is relative to base_path
      * str(len(file))
      * file_content

    Each of these components are separated by a newline character. For example,
    for file = "hello" and the contents "world" the hash would be over:
    ```
    5\n
    hello\n
    5\n
    world\n
    ```

    Args:
      * name: The name of the step.
      * paths: Path of directory/file(s) to compute hash.
      * base_path: Base directory to calculating hash relative to absolute path.
        For e.g. `start_dir` of a recipe execution can be used.
      * test_data: Some default data for this step to return when running under
        simulation. If no test data is provided, we compute test_data as sha256
        of concatenated relative paths passed.

    Returns:
      Hex encoded hash of directory/file content.

    Raises:
      file.Error and ValueError if passed paths input is not str or Path.
    """
    for path in paths:
      if not isinstance(path, (str, config_types.Path)):  # pragma: no cover
        raise ValueError('Expected str or path object, got %r' % type(path))
      self.m.path.assert_absolute(path)

    # TODO(iannucci): recipe engine needs an actual virtual file system.
    rel_paths = [self.m.path.relpath(str(p), str(base_path)) for p in paths]
    if not test_data:
      test_data = hashlib.sha256(b'\n'.join(str(p).encode('utf-8')
                                            for p in rel_paths)).hexdigest()
    result = self._run(
        name, ['compute_hash', base_path] + rel_paths,
        step_test_data=lambda: self.test_api.compute_hash(test_data),
        stdout=self.m.raw_io.output_text())
    sha = result.stdout.strip()
    result.presentation.step_text = 'Hash calculated: %s' % sha
    return sha

  def read_raw(
      self,
      name: str,
      source: config_types.Path | str,
      test_data: bytes = '',
  ) -> bytes:
    """Reads a file as raw data.

    Args:
      * name: The name of the step.
      * source: The path of the file to read.
      * test_data: Some default data for this step to return when running under
        simulation.

    Returns: The unencoded (binary) contents of the file.

    Raises: file.Error
    """
    self.m.path.assert_absolute(source)
    step_test_data = lambda: self.test_api.read_raw(test_data)
    result = self._run(
        name, ['copy', source, self.m.raw_io.output()],
        step_test_data=step_test_data)
    return result.raw_io.output

  def write_raw(
      self,
      name: str,
      dest: config_types.Path | str,
      data: bytes,
  ) -> step_data.StepData:
    """Write the given `data` to `dest`.

    Args:
      * name: The name of the step.
      * dest: The path of the file to write.
      * data: The data to write.

    Raises: file.Error.
    """
    self.m.path.assert_absolute(dest)
    result = self._run(name, ['copy', self.m.raw_io.input(data), dest])
    self.m.path.mock_add_paths(dest)
    return result

  def read_text(
      self,
      name: str,
      source: config_types.Path | str,
      test_data: str = '',
      include_log: bool = True,
  ) -> str:
    """Reads a file as UTF-8 encoded text.

    Args:
      * name: The name of the step.
      * source: The path of the file to read.
      * test_data: Some default data for this step to return when running under
        simulation.
      * include_log: Include step log of read text.

    Returns: The content of the file.

    Raises: file.Error
    """
    self.m.path.assert_absolute(source)
    step_test_data = lambda: self.test_api.read_text(test_data)
    result = self._run(
        name, ['copy', source, self.m.raw_io.output_text()],
        step_test_data=step_test_data)
    text = result.raw_io.output_text
    if include_log:
      result.presentation.logs[self.m.path.basename(source)] = text.splitlines()
    return text

  def write_text(
      self,
      name: str,
      dest: config_types.Path | str,
      text_data: str,
      include_log: bool = True,
  ) -> step_data.StepData:
    """Write the given UTF-8 encoded `text_data` to `dest`.

    Args:
      * name: The name of the step.
      * dest: The path of the file to write.
      * text_data: The UTF-8 encoded data to write.
      * include_log: Include step log of written text.

    Raises: file.Error.
    """
    self.m.path.assert_absolute(dest)
    step = self._run(name, ['copy', self.m.raw_io.input_text(text_data), dest])
    if include_log:
      step.presentation.logs[self.m.path.basename(
          dest)] = text_data.splitlines()
    self.m.path.mock_add_paths(dest)
    return step

  def read_json(
      self,
      name: str,
      source: config_types.Path | str,
      test_data: Any = '',
      include_log: bool = True,
  ) -> Any:
    """Reads a file as UTF-8 encoded json.

    Args:
      * name: The name of the step.
      * source: The path of the file to read.
      * test_data: Some default json serializable data for this step to return
        when running under simulation.
      * include_log: Include step log of read json.

    Returns: The content of the file.

    Raise file.Error
    """
    test_data_text = self.m.json.dumps(test_data, indent=2)
    text = self.read_text(
        name, source, test_data=test_data_text, include_log=include_log)
    return self.m.json.loads(text)

  def write_json(
      self,
      name: str,
      dest: config_types.Path | str,
      data: Any,
      indent: int | str | None = None,
      include_log: bool = True,
      sort_keys: bool = True,
  ) -> step_data.StepData:
    """Write the given json serializable `data` to `dest`.

    Args:
      * name: The name of the step.
      * dest: The path of the file to write.
      * data: Json serializable data to write.
      * indent: The indent of the written JSON. See
        https://docs.python.org/3/library/json.html#json.dump for more details.
      * include_log: Include step log of written json.
      * sort_keys: Sort they keys in `data`. See api.json.input().

    Raises: file.Error.
    """
    text_data = self.m.json.dumps(data, indent=indent, sort_keys=sort_keys)
    return self.write_text(name, dest, text_data, include_log=include_log)

  ProtoMessage = TypeVar('ProtoMessage', bound=google.protobuf.message.Message)

  def read_proto(
      self,
      name: str,
      source: config_types.Path | str,
      msg_class: type[ProtoMessage],
      codec: ProtoCodec,
      test_proto: Any = None,
      include_log: bool = True,
      decoding_kwargs: dict | None = None,
  ) -> ProtoMessage:
    """Reads a file into a proto message.

    Args:
      * name: The name of the step.
      * source: The path of the file to read.
      * msg_class: The message type to be read.
      * codec: The encoder to use.
      * test_proto: A default proto message for this step to return when
        running under simulation.
      * include_log: Include step log of read proto.
      * decoding_kwargs: Passed directly to the chosen encoder. See proto
        module for details.
    """
    self.m.path.assert_absolute(source)
    decoding_kwargs = decoding_kwargs or {}
    if not test_proto:
      test_proto = msg_class()  # test_proto must be a protobuf Message.
    assert type(test_proto) == msg_class
    step_test_data = lambda: self.test_api.read_proto(test_proto)
    result = self._run(
        name, [
            'copy', source,
            self.m.proto.output(
                msg_class, codec, add_json_log=False, **decoding_kwargs)
        ],
        step_test_data=step_test_data)
    if include_log:
      result.presentation.logs[self.m.path.basename(
          source)] = self.m.proto.encode(
              result.proto.output, 'TEXTPB' if codec == 'BINARY' else codec)
    return result.proto.output

  def write_proto(
      self,
      name: str,
      dest: config_types.Path | str,
      proto_msg: google.protobuf.message,
      codec: ProtoCodec,
      include_log: bool = True,
      encoding_kwargs: dict | None = None,
  ) -> step_data.StepData:
    """Writes the given proto message to `dest`.

    Args:
      * name: The name of thhe step.
      * dest: The path of the file to write.
      * proto_msg: Message to write.
      * codec: The encoder to use.
      * include_log: Include step log of written proto.
      * encoding_kwargs: Passed directly to the chosen encoder. See proto
        module for details.
    """
    self.m.path.assert_absolute(dest)
    encoding_kwargs = encoding_kwargs or {}
    step = self._run(
        name,
        ['copy',
         self.m.proto.input(proto_msg, codec, **encoding_kwargs), dest])
    if include_log:
      proto_lines = self.m.proto.encode(
          proto_msg, 'TEXTPB' if codec == 'BINARY' else codec,
          **encoding_kwargs).splitlines()
      step.presentation.logs[self.m.path.basename(dest)] = proto_lines
    self.m.path.mock_add_paths(dest)
    return step

  def glob_paths(
      self,
      name: str,
      source: config_types.Path | str,
      pattern: str,
      include_hidden: bool = False,
      test_data: Sequence[config_types.Path] = (),
  ) -> list[config_types.Path]:
    """Performs glob expansion on `pattern`.

    glob rules for `pattern` follow the same syntax as for the stdlib `glob`
    module with `recursive=True`.

    ```
    e.g. 'a/**/*.py'

    a/b/foo.py => MATCH
    a/b/c/foo.py => MATCH
    a/foo.py => MATCH
    a/b/c/d/e/f/g/h/i/j/foo.py => MATCH
    other/foo.py => NO MATCH
    ```

    Args:
      * name (str): The name of the step.
      * source (Path): The directory whose contents should be globbed.
      * pattern (str): The glob pattern to apply under `source`.
      * include_hidden (bool): Include files beginning with `.`.
      * test_data (iterable[str]): Some default data for this step to return
        when running under simulation. This should be the list of file items
        found in this directory.

    Returns all paths found.

    Raises: file.Error.
    """
    assert isinstance(source, config_types.Path)
    cmd = ['glob', source, pattern]
    if include_hidden:
      cmd.append('--hidden')
    result = self._run(name, cmd, lambda: self.test_api.glob_paths(test_data),
                       self.m.raw_io.output_text())
    ret = [source / x for x in result.stdout.splitlines()]
    result.presentation.logs["glob"] = [str(x) for x in ret]
    return ret

  def remove(
      self,
      name: str,
      source: config_types.Path | str,
  ) -> step_data.StepData:
    """Removes a file.

    Does not raise Error if the file doesn't exist.

    Args:
      * name (str): The name of the step.
      * source (Path): The file to remove.

    Raises: file.Error.
    """
    self.m.path.assert_absolute(source)
    step = self._run(name, ['remove', source])
    self.m.path.mock_remove_paths(source)
    return step

  def listdir(
      self,
      name: str,
      source: config_types.Path | str,
      recursive: bool = False,
      test_data: Sequence[str] = (),
      include_log: bool = True,
  ) -> list[config_types.Path]:
    """Lists all files inside a directory.

    If the source dir contains non-unicode file or dir names, the corresponding
    bad characters will be replace with "?" mark.

    Args:
      * name: The name of the step.
      * source: The directory to list.
      * recursive: If True, do not emit subdirectory entries but recurse
        into them instead, emitting paths relative to `source`. Doesn't follow
        symlinks. Very slow for large directories.
      * test_data: Some default data for this step to return
        when running under simulation. This should be the list of relative
        paths found in this directory.
      * include_log: Include step log of read text.

    Returns list of entries

    Raises: file.Error.
    """
    assert isinstance(source, config_types.Path)
    self.m.path.assert_absolute(source)
    result = self._run(name, ['listdir', source] +
                       (['--recursive'] if recursive else
                        []), lambda: self.test_api.listdir(test_data),
                       self.m.raw_io.output_text())
    ret = [source / x for x in result.stdout.splitlines()]
    if include_log:
      result.presentation.logs['listdir'] = [str(x) for x in ret]
    return ret

  def ensure_directory(
      self,
      name: str,
      dest: config_types.Path | str,
      mode: int = 0o777,
  ) -> step_data.StepData:
    """Ensures that `dest` exists and is a directory.

    Args:
      * name: The name of the step.
      * dest: The directory to ensure.
      * mode: The mode to use if the directory doesn't exist. This method does
        not ensure the mode if the directory already exists (if you need that
        behaviour, file a bug).

    Raises: file.Error if the path exists but is not a directory.
    """
    self.m.path.assert_absolute(dest)
    step = self._run(name, ['ensure-directory', '--mode', oct(mode), dest])
    self.m.path.mock_add_directory(dest)
    return step

  def filesizes(
      self,
      name: str,
      files: Sequence[config_types.Path | str],
      test_data: Sequence[int] | None = None,
  ) -> list[int]:
    """Returns list of filesizes for the given files.

    Args:
      * name: The name of the step.
      * files: Paths to files.
      * test_data: List of filesizes to use in tests.

    Returns size of each file in bytes.
    """
    if test_data is None:
      test_data = [111 * (i + 1) + (i % 3 - 2) * i for i, _ in enumerate(files)]
    for f in files:
      self.m.path.assert_absolute(f)
    result = self._run(name, ['filesizes'] +
                       list(files), lambda: self.test_api.filesizes(test_data),
                       self.m.raw_io.output_text())
    ret = [int(x) for x in result.stdout.strip().splitlines()]
    result.presentation.logs['filesizes'] = [
        '%s: \t%d' % fs for fs in zip(files, ret)
    ]
    return ret

  def rmtree(
      self,
      name: str,
      source: config_types.Path | str,
  ) -> step_data.StepData:
    """Recursively removes a directory.

    This uses a native python on Linux/Mac, and uses `rd` on Windows to avoid
    issues w.r.t. path lengths and read-only attributes. If the directory is
    gone already, this returns without error.

    Args:
      * name: The name of the step.
      * source: The directory to remove.

    Raises: file.Error.
    """
    self.m.path.assert_absolute(source)
    step = self._run(name, ['rmtree', source])
    self.m.path.mock_remove_paths(str(source))
    return step

  def rmcontents(
      self,
      name: str,
      source: config_types.Path | str,
  ) -> step_data.StepData:
    """Similar to rmtree, but removes only contents not the directory.

    This is useful e.g. when removing contents of current working directory.
    Deleting current working directory makes all further getcwd calls fail
    until chdir is called. chdir would be tricky in recipes, so we provide
    a call that doesn't delete the directory itself.

    Args:
      * name (str): The name of the step.
      * source (Path): The directory whose contents should be removed.

    Raises: file.Error.
    """
    self.m.path.assert_absolute(source)
    step = self._run(name, ['rmcontents', source])
    self.m.path.mock_remove_paths(str(source) + self.m.path.sep)
    return step

  def rmglob(
      self,
      name: str,
      source: config_types.Path | str,
      pattern: str,
      recursive: bool = True,
      include_hidden: bool = True,
  ) -> step_data.StepData:
    """Removes all entries in `source` matching the glob `pattern`.

    glob rules for `pattern` follow the same syntax as for the stdlib `glob`
    module with `recursive=True`.

    ```
    e.g. 'a/**/*.py'

    a/b/foo.py => MATCH
    a/b/c/foo.py => MATCH
    a/foo.py => MATCH
    a/b/c/d/e/f/g/h/i/j/foo.py => MATCH
    other/foo.py => NO MATCH
    ```

    Args:
      * name: The name of the step.
      * source: The directory whose contents should be filtered and removed.
      * pattern: The glob pattern to apply under `source`. Anything matching
        this pattern will be removed.
      * recursive: Recursively remove entries under `source`.
          TODO: Remove this option. Use `**` syntax instead.
      * include_hidden: Include files beginning with `.`.
          TODO: Set to False by default to be consistent with file.glob.

    Raises: file.Error.
    """
    self.m.path.assert_absolute(source)
    if recursive and not pattern.startswith('**'):
      pattern = os.path.join('**', pattern)
    cmd = ['rmglob', source, pattern]
    if include_hidden:
      cmd.append('--hidden')
    step = self._run(name, cmd)

    src = str(source)

    def filt(p):
      assert p.startswith(src), (src, p)
      return fnmatch.fnmatch(p[len(src) + 1:].split(os.path.sep)[0], pattern)

    self.m.path.mock_remove_paths(str(source), filt)
    return step

  def symlink(
      self,
      name: str,
      source: config_types.Path | str | recipe_api.Placeholder,
      linkname: config_types.Path | str | recipe_api.Placeholder,
  ) -> step_data.StepData:
    """Creates a symlink on the local filesystem.

    Behaves identically to os.symlink.

    Args:
      * name (str): The name of the step.
      * source (Path|Placeholder): The path to link from.
      * linkname (Path|Placeholder): The destination to link to.

    Raises: file.Error
    """
    self._assert_absolute_path_or_placeholder(source)
    self._assert_absolute_path_or_placeholder(linkname)
    step = self._run(name, ['symlink', source, linkname])
    self.m.path.mock_copy_paths(source, linkname)
    return step

  def symlink_tree(self, root: config_types.Path | str) -> SymlinkTree:
    """Creates a SymlinkTree, given a root directory.

    Args:
      * root: root of a tree of symlinks.
    """
    return SymlinkTree(root, self.m, self.resource('symlink.py'))

  def truncate(
      self,
      name: str,
      path: config_types.Path | str,
      size_mb: int = 100,
  ) -> step_data.StepData:
    """Creates an empty file with path and size_mb on the local filesystem.

    Args:
      * name: The name of the step.
      * path: The absolute path to create.
      * size_mb: The size of the file in megabytes. Defaults to 100

    Raises: file.Error
    """
    self._assert_absolute_path_or_placeholder(path)
    return self._run(name, ['truncate', path, size_mb])

  def flatten_single_directories(
      self,
      name: str,
      path: config_types.Path | str,
  ) -> step_data.StepData:
    """Flattens singular directories, starting at path.

    Example:

        $ mkdir -p dir/which_has/some/singular/subdirs/
        $ touch dir/which_has/some/singular/subdirs/with
        $ touch dir/which_has/some/singular/subdirs/files
        $ flatten_single_directories(dir)
        $ ls dir
        with
        files

    This can be useful when you just want the 'meat' of a very sparse directory
    structure. For example, some tarballs like `foo-1.2.tar.gz` extract all
    their contents into a subdirectory `foo-1.2/`.

    Using this function would essentially move all the actual contents of the
    extracted archive up to the top level directory, removing the need to e.g.
    hard-code/find the subfolder name after extraction (not all archives are
    even named after the subfolder they extract to).

    Args:
      * name: The name of the step.
      * path: The absolute path to begin flattening.

    Raises: file.Error
    """
    self.m.path.assert_absolute(path)
    return self._run(name, ['flatten_single_directories', path])
