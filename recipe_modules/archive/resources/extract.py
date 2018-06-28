# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Standalone Python script to extract an archive. Intended to be used by
the 'archive' recipe module internally. Should not be used elsewhere.
"""

import argparse
import copy
import json
import operator
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile


def untar(archive_file, output, stats, safe):
  """Untars an archive using 'tarfile' python module.

  Works everywhere where Python works (Windows and POSIX).

  Args:
    archive_file: absolute path to an archive to untar.
    output: existing directory to untar to.
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

      print 'Extracting %r' % (tarinfo.name,)
      stats['extracted']['filecount'] += 1
      stats['extracted']['bytes'] += tarinfo.size
      em(tarinfo, targetpath)
    tf._extract_member = _extract_member
    tf.extractall(output)


def unzip(zip_file, output, stats):
  """Unzips an archive using 'zipfile' python module.

  Works everywhere where Python works (Windows and POSIX).

  Args:
    zip_file: absolute path to an archive to unzip.
    output: existing directory to unzip to.
  """
  with zipfile.ZipFile(zip_file) as zf:
    for zipinfo in zf.infolist():
      print 'Extracting %s' % zipinfo.filename
      stats['extracted']['filecount'] += 1
      stats['extracted']['bytes'] += zipinfo.file_size
      zf.extract(zipinfo, output)


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

    if file_type == 'zip':
      # NOTE: zipfile module is always safe in python 2.7.4+... it mangles
      # extracted file names to ensure they don't escape the extraction root.
      unzip(archive_file, output, stats)
    else:
      untar(archive_file, output, stats, safe_mode)

    json.dump(stats, opts.json_output)
  except:
    shutil.rmtree(output, ignore_errors=True)
    raise
  return 0


if __name__ == '__main__':
  sys.exit(main())
