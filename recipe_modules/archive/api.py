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
      # Archive root/file and root/directory/**
      (api.archive.package(root).
          with_file(root.join('file')).
          with_dir(root.join('directory')).
          archive('archive step', output, 'tbz'))

      # Archive root/**
      zip_path = (
        api.archive.package(root).
        archive('archive step', api.path['start_dir'].join('output.zip'))
      )

    Args:
      root: a directory that would become root of a package, all files added to
          an archive must be Paths which are under this directory. If no files
          or directories are added with 'with_file' or 'with_dir', the entire
          root directory is packaged.

    Returns:
      Package object.
    """
    return Package(self._archive_impl, root)

  def extract(self, step_name, archive_file, output, mode='safe'):
    """Step to uncompress |archive_file| into |output| directory.

    Archive will be unpacked to |output| so that root of an archive is in
    |output|, i.e. archive.tar/file.txt will become |output|/file.txt.

    Step will FAIL if |output| already exists.

    Args:
      step_name (str): display name of a step.
      archive_file (Path): path to an archive file to uncompress, MUST exist.
      output (Path): path to a directory to unpack to, MUST NOT exist.
      mode (str): Must be either 'safe' or 'unsafe'. In safe mode, if the
        archive attempts to extract files which would escape the extraction
        `output` location, the extraction will fail (raise StepException)
        which contains a member `StepException.archive_skipped_files` (all
        other files will be extracted normally). If 'unsafe', then tarfiles
        containing paths escaping `output` will be extracted as-is.
    """
    assert mode in ('safe', 'unsafe'), 'Unknown mode %r' % (mode,)

    step_result = self.m.python(
      step_name,
      self.resource('extract.py'),
      [
        '--json-input', self.m.json.input({
          'output': str(output),
          'archive_file': str(archive_file),
          'safe_mode': mode == 'safe',
        }),
        '--json-output', self.m.json.output(),
      ],
      step_test_data=lambda: self.m.json.test_api.output({
        'extracted': {
          'filecount': 1337,
          'bytes': 0xbadc0ffee,
        },
      }))
    self.m.path.mock_add_paths(output)
    j = step_result.json.output
    if j.get('extracted', {}).get('filecount'):
      stat = j['extracted']
      step_result.presentation.step_text += (
        '<br/>extracted %s files - %.02f MB' % (
          stat['filecount'], stat['bytes'] / (1000.0**2)))
    if j.get('skipped', {}).get('filecount'):
      stat = j['skipped']
      step_result.presentation.step_text += (
        '<br/>SKIPPED %s files - %.02f MB' % (
          stat['filecount'], stat['bytes'] / (1000.0**2)))
      step_result.presentation.logs['skipped files'] = stat['names']
      step_result.presentation.status = self.m.step.FAILURE
      ex = self.m.step.StepFailure(step_name)
      ex.archive_skipped_files = stat['names']
      raise ex

  def _archive_impl(self, root, entries, step_name, output, archive_type):
    assert entries, 'entries is empty!'

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
  """Used to gather a list of files to archive.

  Construct this with api.archive.package().

  If no 'with_file' or 'with_dir' calls are made, this defaults to including
  the entire root in the archive.
  """

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

    If no 'with_file' or 'with_dir' calls were made, this will zip the entire
    root by default.

    Args:
      output: path to an archive file to create.
      archive_type: The type of archive to create. This may be:
        tar, tgz, tbz, zip. If None, will be inferred from the extension of
        output.

    Returns:
      `output`, for convenience.
    """
    entries = self._entries or [
      {'type': 'dir', 'path': str(self._root)}
    ]
    self._archive_callback(self._root, entries, step_name, output,
                           archive_type)
    return output
