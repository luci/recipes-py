# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Standalone Python script to archive a set of files. Intended to be used by
the 'archive' recipe module internally. Should not be used elsewhere.
"""

import json
import os
import subprocess
import sys
import tarfile
import zipfile


def zip_opener(path):
  """Opens a zipfile to write and adds .name and .add attributes to make it
  duck-type compatible with a tarfile.TarFile for the purposes of archive."""
  zf = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)
  zf.name = zf.filename
  zf.add = zf.write
  return zf


def archive(out, root, entries):
  """Archives set of files and directories to `out`.

  Works everywhere where python works (Windows and POSIX).

  Args:
    out: tarfile.TarFile (or duck-type compatible ZipFile)
    root: absolute path to a directory that will become a root of the archive.
    entries: list of dicts, describing what to tar, see tar/api.py.

  Returns:
    Exit code (0 on success).
  """
  def add(path):
    assert path.startswith(root), path
    # Do not add itself to archive.
    if path == out.name:
      return
    archive_name = path[len(root):]
    print 'Adding %s' % archive_name
    out.add(path, archive_name)

  for entry in entries:
    tp = entry['type']
    path = entry['path']
    if tp == 'file':
      add(path)
    elif tp == 'dir':
      for cur, _, files in os.walk(path):
        for name in files:
          add(os.path.join(cur, name))
    else:
      raise AssertionError('Invalid entry type: %s' % (tp,))


OPENER_FUNCS = {
  'tar': lambda path: tarfile.open(path, 'w'),
  'tgz': lambda path: tarfile.open(path, 'w|gz'),
  'tbz': lambda path: tarfile.open(path, 'w|bz2'),
  'zip': zip_opener,
}


def main():
  # See tar/api.py, def tar(...) for format of |data|.
  data = json.load(sys.stdin)
  entries = data['entries']
  output = data['output']
  archive_type = data['archive_type']
  root = os.path.join(data['root'], '')

  # Archive root directory should exist and be an absolute path.
  assert os.path.exists(root), root
  assert os.path.isabs(root), root

  # Output tar path should be an absolute path.
  assert os.path.isabs(output), output

  print 'Archiving %s -> %s (%s)...' % (root, output, archive_type)
  # TODO(iannucci): use CIPD to fetch native clients instead of using python
  # builtins.
  try:
    with OPENER_FUNCS[archive_type](output) as arc:
      archive(arc, root, entries)
    print 'Archive size: %.1f KB' % (os.stat(output).st_size / 1024.0,)
    return 0
  except:
    try:
      os.remove(output)
    except:  # pylint: disable=bare-except
      pass
    raise
  return 1


if __name__ == '__main__':
  sys.exit(main())
