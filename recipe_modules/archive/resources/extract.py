# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Standalone Python script to extract an archive. Intended to be used by
the 'archive' recipe module internally. Should not be used elsewhere.
"""

import argparse
import copy
import fnmatch
import json
import operator
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
import zipfile


if os.name == 'nt':
  def unc_path(path):
    return '\\\\?\\' + os.path.abspath(path)
else:
  def unc_path(path):
    return path


def untar(archive_file, output, stats, safe, include_filter):
  """Untars an archive using 'tarfile' python module.

  Works everywhere where Python works (Windows and POSIX).

  Args:
    archive_file: absolute path to an archive to untar.
    output: existing directory to untar to.
    stats: the stats dict (see main() for its form)
    safe (bool): If True, skips extracting files which would escape `output`.
    include_filter (fn(path): bool): A function which is given the archive
      path and should return True if we should extract it.
  """
  with tarfile.open(archive_file, 'r|*') as tf:
    # monkeypatch the TarFile object to allow printing messages for each
    # extracted file. extractall makes a single linear pass over the tarfile;
    # other naive implementations (such as `getmembers`) end up doing lots of
    # random access over the file.
    em = tf._extract_member
    def _extract_member(tarinfo, targetpath):
      if safe and not os.path.abspath(targetpath).startswith(output):
        print 'Skipping %r (would escape root)' % (tarinfo.name,)
        stats['skipped']['filecount'] += 1
        stats['skipped']['bytes'] += tarinfo.size
        stats['skipped']['names'].append(tarinfo.name)
        return

      if not include_filter(tarinfo.name):
        print 'Skipping %r (does not match include_files)' % (tarinfo.name,)
        return

      print 'Extracting %r' % (tarinfo.name,)
      stats['extracted']['filecount'] += 1
      stats['extracted']['bytes'] += tarinfo.size
      em(tarinfo, unc_path(targetpath))
    tf._extract_member = _extract_member
    tf.extractall(output)


def unzip(zip_file, output, stats, include_filter):
  """Unzips an archive using 'zipfile' python module.

  Works everywhere where Python works (Windows and POSIX).

  Args:
    zip_file: absolute path to an archive to unzip.
    output: existing directory to unzip to.
    stats: the stats dict (see main() for its form)
    include_filter (fn(path): bool): A function which is given the archive
      path and should return True if we should extract it.
  """
  with zipfile.ZipFile(zip_file) as zf:
    for zipinfo in zf.infolist():
      if not include_filter(zipinfo.filename):
        print 'Skipping %r (does not match include_files)' % (zipinfo.filename,)
        continue

      print 'Extracting %s' % zipinfo.filename
      stats['extracted']['filecount'] += 1
      stats['extracted']['bytes'] += zipinfo.file_size
      zf.extract(zipinfo, unc_path(output))


def main():
  # See archive/api.py, def extract(...) for format of |data|.
  ap = argparse.ArgumentParser()
  ap.add_argument('--json-input', type=argparse.FileType('r'))
  ap.add_argument('--json-output', type=argparse.FileType('w'))
  opts = ap.parse_args()

  data = json.load(opts.json_input)
  output = data['output']
  archive_file = data['archive_file']
  safe_mode = data['safe_mode']
  include_files = data['include_files']

  # Archive path should exist and be an absolute path to a file.
  assert os.path.isabs(archive_file), archive_file
  assert os.path.isfile(archive_file), archive_file

  # Output path should be an absolute path, and should NOT exist.
  assert os.path.isabs(output), output
  assert not os.path.exists(output), output
  # Normalize it to end with a path separator.
  output = os.path.join(output, '')

  file_type = 'zip' if archive_file.endswith('.zip') else 'tar'

  print 'Extracting %s (%s) -> %s ...' % (archive_file, file_type, output)
  try:
    os.makedirs(output)

    stats = {
      'extracted': {
        'filecount': 0,
        'bytes': 0,
      },
      'skipped': {
        'filecount': 0,
        'bytes': 0,
        'names': [],
      },
    }

    include_filter = lambda _path: True
    if include_files:
      def include_filter(path):
        path = posixpath.normpath(path)
        if path.startswith('./'):
          path = path[2:]
        for pattern in include_files:
          if fnmatch.fnmatch(path, pattern):
            return True
        return False

    if file_type == 'zip':
      # NOTE: zipfile module is always safe in python 2.7.4+... it mangles
      # extracted file names to ensure they don't escape the extraction root.
      unzip(archive_file, output, stats, include_filter)
    else:
      untar(archive_file, output, stats, safe_mode, include_filter)

    json.dump(stats, opts.json_output)
  except:
    shutil.rmtree(output, ignore_errors=True)
    raise
  return 0


if __name__ == '__main__':
  sys.exit(main())
