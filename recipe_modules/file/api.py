# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""File manipulation (read/write/delete/glob) methods."""

from recipe_engine import config_types
from recipe_engine import recipe_api

import fnmatch
import hashlib
import os


class SymlinkTree(object):
  """A representation of a tree of symlinks."""

  def __init__(self, root, api, symlink_resource):
    """See FileApi.symlink_tree for the public constructor."""
    assert root and isinstance(root, config_types.Path)
    self._root = root
    self._api = api
    self._resource = symlink_resource
    #  dict[Path]list(Path): Maps target to a list of linknames.
    self._link_map = {}
    #  dict[Path]Path: Maps a linkname to its target.
    self._reverse_map = {}

  @property
  def root(self):
    """The root (Path) of the symlink tree."""
    return self._root

  def register_link(self, target, linkname):
    """Registers a pair of paths to symlink.

    Args:
      * target (Path) - The file/directory to which the symlink will point.
      * linkname (Path) - The location of the symlink. Must be a child of the
          SymlinkTree's `root`. It is an error to register two links with the
          same linkname.
    """
    assert (isinstance(target, config_types.Path) and
            isinstance(linkname, config_types.Path))
    if linkname in self._link_map.get(target, ()):
      return
    else:
      assert linkname not in self._reverse_map, (
          '%s is alreadly linked to %s' %
          (linkname, self._reverse_map[linkname]))

    assert self.root.is_parent_of(linkname), (
        '%s is not within the root directory %s' % (linkname, self.root))
    self._link_map.setdefault(target, []).append(linkname)
    self._reverse_map[linkname] = target

  def create_links(self, name):
    """Creates all registered symlinks on disk.

    Args:
      * name (str) - The name of the step.
    """
    for target, linknames in self._link_map.iteritems():
      for linkname in linknames:
        self._api.path.mock_copy_paths(target, linkname)
    self._api.python(
        name,
        self._resource,
        args=[
            '--link-json',
            self._api.json.input({
                str(target): linkname
                for target, linkname in self._link_map.iteritems()
            }),
        ],
        infra_step=True)


# TODO(iannucci): Introduce the concept of a 'native step' and implement these
# directly in the current python interpreter without the need for a subprocess
# invocation.


class FileApi(recipe_api.RecipeApi):

  class Error(recipe_api.StepFailure):
    """Error is a StepFailure, except that it also contains an errno field
    indicating the errno name (i.e. 'EEXIST') of the underlying error.
    """

    def __init__(self, step_name, errno_name, message):
      reason = 'Step(%r) failed %r with: %s' % (step_name, errno_name, message)
      super(FileApi.Error, self).__init__(reason)
      self.errno_name = errno_name

  def _assert_absolute_path_or_placeholder(self, path_or_placeholder):
    if isinstance(path_or_placeholder, recipe_api.Placeholder):
      # We assume that all Placeholder classes will render to an absolute path,
      # as this is part of their api contract.
      return True
    return self.m.path.assert_absolute(path_or_placeholder)

  def _run(self, name, args, step_test_data=None, stdout=None):
    if not step_test_data:
      step_test_data = self.test_api.errno
    args = ['--json-output', self.m.json.output(add_json_log=False)] + args
    result = self.m.python(
        name,
        self.resource('fileutil.py'),
        args=args,
        step_test_data=step_test_data,
        stdout=stdout,
        infra_step=True,
        venv=True)
    j = result.json.output
    if not j['ok']:
      result.presentation.status = self.m.step.FAILURE
      result.presentation.step_text = j['message']
      # pylint thinks this isn't a standard exception... silly pylint.
      # pylint: disable=nonstandard-exception
      raise self.Error(name, j['errno_name'], j['message'])
    return result

  def copy(self, name, source, dest):
    """Copies a file (including mode bits) from source to destination on the
    local filesystem.

    Behaves identically to shutil.copy.

    Args:
      * name (str) - The name of the step.
      * source (Path|Placeholder) - The path to the file you want to copy.
      * dest (Path|Placeholder) - The path to the destination file name. If this
        path exists and is a directory, the basename of `source` will be
        appended to derive a path to a destination file.

    Raises file.Error
    """
    self._assert_absolute_path_or_placeholder(source)
    self._assert_absolute_path_or_placeholder(dest)
    self._run(name, ['copy', source, dest])
    self.m.path.mock_copy_paths(source, dest)

  def copytree(self, name, source, dest, symlinks=False):
    """Recursively copies a directory tree.

    Behaves identically to shutil.copytree.
    `dest` must not exist.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The path of the directory to copy.
      * dest (Path) - The place where you want the recursive copy to show up.
        This must not already exist.
      * symlinks (bool) - Preserve symlinks. No effect on Windows.

    Raises file.Error
    """
    self.m.path.assert_absolute(source)
    self.m.path.assert_absolute(dest)
    args = ['--symlinks'] if symlinks else []
    self._run(name, ['copytree'] + args + [source, dest])
    self.m.path.mock_copy_paths(source, dest)

  def move(self, name, source, dest):
    """Moves a file or directory.

    Behaves identically to shutil.move.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The path of the item to move.
      * dest (Path) - The new name of the item.

    Raises file.Error
    """
    self.m.path.assert_absolute(source)
    self.m.path.assert_absolute(dest)
    self._run(name, ['move', source, dest])
    self.m.path.mock_copy_paths(source, dest)
    self.m.path.mock_remove_paths(source)

  def compute_hash(self, name, paths, base_path, test_data=''):
    """Computes hash of contents of a directory/file.

    This function will compute hash by including following info of a file:
      * str(len(path))  // path is relative to base_path
      * path            // path is relative to base_path
      * str(len(file))
      * file_content

    Each of these components are separated by a newline character.

    e.g. for file = "hello" and the contents "world" the hash would be over

      5\n
      hello\n
      5\n
      world\n

    Args:
      * name (str) - The name of the step.
      * paths (list[Path|str]) - Path of directory/file(s) to compute hash.
      * base_path (Path|str) - Base directory to calculating hash relative to
        absolute path. For e.g. `start_dir` of a recipe execution can be used.
      * test_data (str) - Some default data for this step to return when running
        under simulation. If no test data is provided, we compute test_data as
        sha256 of concatenated relative paths passed.

    Returns (str) - Hex encoded hash of directory/file content.

    Raises file.Error and ValueError if passed paths input is not str or Path.
    """
    for path in paths:
      if not isinstance(path, (str, config_types.Path)):  # pragma: no cover
        raise ValueError('Expected str or path object, got %r' % type(path))
      self.m.path.assert_absolute(path)

    # TODO(iannucci): recipe engine needs an actual virtual file system.
    rel_paths = [self.m.path.relpath(str(p), str(base_path)) for p in paths]
    if not test_data:
      test_data = hashlib.sha256('\n'.join(map(str, rel_paths))).hexdigest()
    result = self._run(
        name, ['compute_hash', base_path] + rel_paths,
        step_test_data=lambda: self.test_api.compute_hash(test_data),
        stdout=self.m.raw_io.output_text())
    sha = result.stdout.strip()
    result.presentation.step_text = 'Hash calculated: %s' % sha
    return sha

  def read_raw(self, name, source, test_data=''):
    """Reads a file as raw data.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The path of the file to read.
      * test_data (str) - Some default data for this step to return when running
        under simulation.

    Returns (str) - The unencoded (binary) contents of the file.

    Raises file.Error
    """
    self.m.path.assert_absolute(source)
    step_test_data = lambda: self.test_api.read_raw(test_data)
    result = self._run(
        name, ['copy', source, self.m.raw_io.output()],
        step_test_data=step_test_data)
    return result.raw_io.output

  def write_raw(self, name, dest, data, include_log=True):
    """Write the given `data` to `dest`.

    Args:
      * name (str) - The name of the step.
      * dest (Path) - The path of the file to write.
      * data (str) - The data to write.
      * include_log (bool) - Include step log of written data.

    Raises file.Error.
    """
    self.m.path.assert_absolute(dest)
    step = self._run(name, ['copy', self.m.raw_io.input(data), dest])
    if include_log:
      step.presentation.logs[self.m.path.basename(dest)] = data.splitlines()
    self.m.path.mock_add_paths(dest)

  def read_text(self, name, source, test_data=''):
    """Reads a file as UTF-8 encoded text.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The path of the file to read.
      * test_data (str) - Some default data for this step to return when running
        under simulation.

    Returns (str) - The content of the file.

    Raises file.Error
    """
    self.m.path.assert_absolute(source)
    step_test_data = lambda: self.test_api.read_text(test_data)
    result = self._run(
        name, ['copy', source, self.m.raw_io.output_text()],
        step_test_data=step_test_data)
    text = result.raw_io.output_text
    result.presentation.logs[self.m.path.basename(source)] = text.splitlines()
    return text

  def write_text(self, name, dest, text_data, include_log=True):
    """Write the given UTF-8 encoded `text_data` to `dest`.

    Args:
      * name (str) - The name of the step.
      * dest (Path) - The path of the file to write.
      * text_data (str) - The UTF-8 encoded data to write.
      * include_log (bool) - Include step log of written text.

    Raises file.Error.
    """
    self.m.path.assert_absolute(dest)
    step = self._run(name, ['copy', self.m.raw_io.input_text(text_data), dest])
    if include_log:
      step.presentation.logs[self.m.path.basename(
          dest)] = text_data.splitlines()
    self.m.path.mock_add_paths(dest)

  def read_json(self, name, source, test_data=''):
    """Reads a file as UTF-8 encoded json.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The path of the file to read.
      * test_data (object) - Some default json serializable data for this step
        to return when running under simulation.

    Returns (object) - The content of the file.

    Raise file.Error
    """
    test_data_text = self.m.json.dumps(test_data)
    text = self.read_text(name, source, test_data=test_data_text)
    return self.m.json.loads(text)

  def write_json(self, name, dest, data, indent=None):
    """Write the given json serializable `data` to `dest`.

    Args:
      * name (str) - The name of the step.
      * dest (Path) - The path of the file to write.
      * data (object) - Json serializable data to write.
      * indent (None|int|str) - The indent of the written JSON. See
        https://docs.python.org/3/library/json.html#json.dump for more details.

    Raises file.Error.
    """
    text_data = self.m.json.dumps(data, indent=indent)
    self.write_text(name, dest, text_data)

  def read_proto(self, name, source, msg_class, codec, test_proto=None):
    """Reads a file into a proto message.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The path of the file to read.
      * msg_class (protobuf Message subclass) - The message type to be read.
      * codec ('BINARY'|'JSONPB'|'TEXTPB') - The encoder to use.
      * test_proto (protobuf Message) - A default proto message for this step to
        return when running under simulation.
    """
    self.m.path.assert_absolute(source)
    if not test_proto:
      test_proto = msg_class()  # test_proto must be a protobuf Message.
    assert type(test_proto) == msg_class
    step_test_data = lambda: self.test_api.read_proto(test_proto)
    result = self._run(
        name, ['copy', source, self.m.proto.output(msg_class, codec)],
        step_test_data=step_test_data)
    return result.proto.output

  def write_proto(self, name, dest, proto_msg, codec, include_log=True):
    """Write the given proto message to `dest`.

    Args:
      * name (str) - The name of thhe step.
      * dest (Path) - The path of the file to write.
      * proto_msg (protobuf Message) - Message to write.
      * codec ('BINARY'|'JSONPB'|'TEXTPB') - The encoder to use.
      * include_log (bool) - Include step log of written text.
    """
    self.m.path.assert_absolute(dest)
    step = self._run(name, ['copy', self.m.proto.input(proto_msg, codec), dest])
    if include_log:
      proto_lines = str(proto_msg).splitlines()
      step.presentation.logs[self.m.path.basename(dest)] = proto_lines
    self.m.path.mock_add_paths(dest)

  def glob_paths(self,
                 name,
                 source,
                 pattern,
                 include_hidden=False,
                 test_data=()):
    """Performs glob expansion on `pattern`.

    glob rules for `pattern` follow the same syntax as for the `python-glob2`
    module, which supports '**' syntax.

    ```
    e.g. 'a/**/*.py'

    a/b/foo.py => MATCH
    a/b/c/foo.py => MATCH
    a/foo.py => MATCH
    a/b/c/d/e/f/g/h/i/j/foo.py => MATCH
    other/foo.py => NO MATCH
    ```

    Args:
      * name (str) - The name of the step.
      * source (Path) - The directory whose contents should be globbed.
      * pattern (str) - The glob pattern to apply under `source`.
      * include_hidden (bool) - Include files beginning with `.`.
      * test_data (iterable[str]) - Some default data for this step to return
        when running under simulation. This should be the list of file items
        found in this directory.

    Returns list[Path] - All paths found.

    Raises file.Error.
    """
    assert isinstance(source, config_types.Path)
    cmd = ['glob', source, pattern]
    if include_hidden:
      cmd.append('--hidden')
    result = self._run(name, cmd, lambda: self.test_api.glob_paths(test_data),
                       self.m.raw_io.output_text())
    ret = [
        source.join(*x.split(self.m.path.sep))
        for x in result.stdout.splitlines()
    ]
    result.presentation.logs["glob"] = map(str, ret)
    return ret

  def remove(self, name, source):
    """Remove a file.

    Does not raise Error if the file doesn't exist.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The file to remove.

    Raises file.Error.
    """
    self.m.path.assert_absolute(source)
    self._run(name, ['remove', source])
    self.m.path.mock_remove_paths(source)

  def listdir(self, name, source, recursive=False, test_data=()):
    """List all files inside a directory.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The directory to list.
      * recursive (bool) - If True, do not emit subdirectory entries but recurse
        into them instead, emitting paths relative to `source`. Doesn't follow
        symlinks. Very slow for large directories.
      * test_data (iterable[str]) - Some default data for this step to return
        when running under simulation. This should be the list of relative paths
        found in this directory.

    Returns list[Path]

    Raises file.Error.
    """
    assert isinstance(source, config_types.Path)
    self.m.path.assert_absolute(source)
    result = self._run(name, ['listdir', source] +
                       (['--recursive'] if recursive else
                        []), lambda: self.test_api.listdir(test_data),
                       self.m.raw_io.output_text())
    ret = [
        source.join(*x.split(self.m.path.sep))
        for x in result.stdout.splitlines()
    ]
    result.presentation.logs['listdir'] = map(str, ret)
    return ret

  def ensure_directory(self, name, dest, mode=0777):
    """Ensures that `dest` exists and is a directory.

    Args:
      * name (str) - The name of the step.
      * dest (Path) - The directory to ensure.
      * mode (int) - The mode to use if the directory doesn't exist. This method
        does not ensure the mode if the directory already exists (if you need
        that behaviour, file a bug).

    Raises file.Error if the path exists but is not a directory.
    """
    self.m.path.assert_absolute(dest)
    self._run(name, ['ensure-directory', '--mode', oct(mode), dest])
    self.m.path.mock_add_paths(dest)

  def filesizes(self, name, files, test_data=None):
    """Returns list of filesizes for the given files.

    Args:
      * name (str) - The name of the step.
      * files (list[Path]) - Paths to files.

    Returns list[int], size of each file in bytes.
    """
    if test_data is None:
      test_data = [111 * (i + 1) + (i % 3 - 2) * i for i, _ in enumerate(files)]
    for f in files:
      self.m.path.assert_absolute(f)
    result = self._run(name, ['filesizes'] +
                       list(files), lambda: self.test_api.filesizes(test_data),
                       self.m.raw_io.output_text())
    ret = map(int, result.stdout.strip().splitlines())
    result.presentation.logs['filesizes'] = [
        '%s: \t%d' % fs for fs in zip(files, ret)
    ]
    return ret

  def rmtree(self, name, source):
    """Recursively removes a directory.

    This uses a native python on Linux/Mac, and uses `rd` on Windows to avoid
    issues w.r.t. path lengths and read-only attributes. If the directory is
    gone already, this returns without error.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The directory to remove.

    Raises file.Error.
    """
    self.m.path.assert_absolute(source)
    self._run(name, ['rmtree', source])
    self.m.path.mock_remove_paths(str(source))

  def rmcontents(self, name, source):
    """Similar to rmtree, but removes only contents not the directory.

    This is useful e.g. when removing contents of current working directory.
    Deleting current working directory makes all further getcwd calls fail
    until chdir is called. chdir would be tricky in recipes, so we provide
    a call that doesn't delete the directory itself.

    Args:
      * name (str) - The name of the step.
      * source (Path) - The directory whose contents should be removed.

    Raises file.Error.
    """
    self.m.path.assert_absolute(source)
    self._run(name, ['rmcontents', source])
    self.m.path.mock_remove_paths(str(source) + self.m.path.sep)

  def rmglob(self, name, source, pattern, recursive=True, include_hidden=True):
    """Removes all entries in `source` matching the glob `pattern`.

    glob rules for `pattern` follow the same syntax as for the `python-glob2`
    module, which supports '**' syntax.

    ```
    e.g. 'a/**/*.py'

    a/b/foo.py => MATCH
    a/b/c/foo.py => MATCH
    a/foo.py => MATCH
    a/b/c/d/e/f/g/h/i/j/foo.py => MATCH
    other/foo.py => NO MATCH
    ```

    Args:
      * name (str) - The name of the step.
      * source (Path) - The directory whose contents should be filtered and
        removed.
      * pattern (str) - The glob pattern to apply under `source`. Anything
        matching this pattern will be removed.
      * recursive (bool) - Recursively remove entries under `source`.
          TODO: Remove this option. Use `**` syntax instead.
      * include_hidden (bool) - Include files beginning with `.`.
          TODO: Set to False by default to be consistent with file.glob.

    Raises file.Error.
    """
    self.m.path.assert_absolute(source)
    if recursive and not pattern.startswith('**'):
      pattern = os.path.join('**', pattern)
    cmd = ['rmglob', source, pattern]
    if include_hidden:
      cmd.append('--hidden')
    self._run(name, cmd)

    src = str(source)

    def filt(p):
      assert p.startswith(src), (src, p)
      return fnmatch.fnmatch(p[len(src) + 1:].split(os.path.sep)[0], pattern)

    self.m.path.mock_remove_paths(str(source), filt)

  def symlink(self, name, source, linkname):
    """Creates a symlink on the local filesystem.

    Behaves identically to os.symlink.

    Args:
      * name (str) - The name of the step.
      * source (Path|Placeholder) - The path to link from.
      * linkname (Path|Placeholder) - The destination to link to.

    Raises file.Error
    """
    self._assert_absolute_path_or_placeholder(source)
    self._assert_absolute_path_or_placeholder(linkname)
    self._run(name, ['symlink', source, linkname])
    self.m.path.mock_copy_paths(source, linkname)

  def symlink_tree(self, root):
    """Creates a SymlinkTree, given a root directory.

    Args:
      * root (Path): root of a tree of symlinks.
    """
    return SymlinkTree(root, self.m, self.resource('symlink.py'))

  def truncate(self, name, path, size_mb=100):
    """Creates an empty file with path and size_mb on the local filesystem.

    Args:
      * name (str) - The name of the step.
      * path (Path|str) - The absolute path to create.
      * size_mb (int) - The size of the file in megabytes. Defaults to 100

    Raises file.Error
    """
    self._assert_absolute_path_or_placeholder(path)
    self._run(name, ['truncate', path, size_mb])

  def flatten_single_directories(self, name, path):
    """Flattens singular directories, starting at path.

    Example:

        $ mkdir -p dir/which_has/some/singlular/subdirs/
        $ touch dir/which_has/some/singlular/subdirs/with
        $ touch dir/which_has/some/singlular/subdirs/files
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
      * name (str) - The name of the step.
      * path (Path|str) - The absolute path to begin flattening.

    Raises file.Error
    """
    self.m.path.assert_absolute(path)
    self._run(name, ['flatten_single_directories', path])
