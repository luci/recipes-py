# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class ArchiveApi(recipe_api.RecipeApi):
  """Provides steps to manipulate archive files (tar, zip, etc.)."""

  ARCHIVE_TYPES = ('tar', 'tgz', 'tbz', 'zip')

  def package(self, root):
    """Returns Package object that can be used to compress a set of files.

    Usage:
      (api.archive.make(root).
          with_file(root.join('file')).
          with_dir(root.join('directory')).
          archive('archive step', output, 'tbz'))

    Args:
      root: a directory that would become root of a package, all files added to
          an archive will have archive paths relative to this directory.

    Returns:
      Package object.
    """
    return Package(self._archive_impl, root)

  def extract(self, step_name, archive_file, output):
    """Step to uncompress |archive_file| into |output| directory.

    Archive will be unpacked to |output| so that root of an archive is in
    |output|, i.e. archive.tar/file.txt will become |output|/file.txt.

    Step will FAIL if |output| already exists.

    Args:
      step_name: display name of a step.
      archive_file: path to an archive file to uncompress, MUST exist.
      output: path to a directory to unpack to, MUST NOT exist.
    """
    self.m.python(
      name=step_name,
      script=self.resource('extract.py'),
      stdin=self.m.json.input({
        'output': str(output),
        'archive_file': str(archive_file),
      }))

  def _archive_impl(self, root, entries, step_name, output, archive_type):
    if archive_type is None:
      base, ext = self.m.path.splitext(output)
      if base.endswith('.tar'):
        ext = '.tar' + ext
      archive_type = {
        '.tbz': 'tbz',
        '.tbz2': 'tbz',
        '.tb2': 'tbz',
        '.tar.bz2': 'tbz',

        '.tgz': 'tgz',
        '.tar.gz': 'tgz',

        '.tar': 'tar',

        '.zip': 'zip',
      }.get(ext)
      assert archive_type is not None, (
        'Unable to infer archive_type from extension: %r' % (ext,))

    assert archive_type in self.ARCHIVE_TYPES, (
      'Unsupported archive_type %r' % (archive_type,))

    script_input = {
      'entries': entries,
      'output': str(output),
      'archive_type': archive_type,
      'root': str(root),
    }
    self.m.python(
        name=step_name,
        script=self.resource('archive.py'),
        stdin=self.m.json.input(script_input))
    self.m.path.mock_add_paths(output)


class Package(object):
  """Used to gather a list of files to archive."""

  def __init__(self, archive_callback, root):
    self._archive_callback = archive_callback
    self._root = root
    self._entries = []

  @property
  def root(self):
    return self._root

  def with_file(self, path):
    """Stages single file to be added to the package.

    Args:
      path: absolute path to a file, should be in |root| subdirectory.

    Returns:
      `self` to allow chaining.
    """
    assert self._root.is_parent_of(path), (
      '%r is not a parent of %r' % (self._root, path))
    self._entries.append({
      'type': 'file',
      'path': str(path),
    })
    return self

  def with_dir(self, path):
    """Stages a directory with all its content to be added to the package.

    Args:
      path: absolute path to a directory, should be in |root| subdirectory.

    Returns:
      `self` to allow chaining.
    """
    assert self._root.is_parent_of(path) or path == self._root, (
      '%r is not a parent of %r' % (self._root, path))
    self._entries.append({
      'type': 'dir',
      'path': str(path),
    })
    return self

  def archive(self, step_name, output, archive_type=None):
    """Archives all staged files to an archive file indicated by `output`.

    Args:
      output: path to an archive file to create.
      archive_type: The type of archive to create. This may be:
        tar, tgz, tbz, zip. If None, will be inferred from the extension of
        output.

    Returns:
      `output`, for convenience.
    """
    self._archive_callback(self._root, self._entries, step_name, output,
                           archive_type)
    return output
