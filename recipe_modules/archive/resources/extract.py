# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Standalone Python script to extract an archive. Intended to be used by
the 'archive' recipe module internally. Should not be used elsewhere.
"""

import copy
import json
import operator
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile


def untar(archive_file, output):
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
      print 'Extracting %s' % tarinfo.name
      return em(tarinfo, targetpath)
    tf._extract_member = _extract_member
    tf.extractall(output)


def unzip(zip_file, output):
  """Unzips an archive using 'zipfile' python module.

  Works everywhere where Python works (Windows and POSIX).

  Args:
    zip_file: absolute path to an archive to unzip.
    output: existing directory to unzip to.
  """
  with zipfile.ZipFile(zip_file) as zf:
    for zipinfo in zf.infolist():
      print 'Extracting %s' % zipinfo.filename
      zf.extract(zipinfo, output)


def main():
  # See archive/api.py, def extract(...) for format of |data|.
  data = json.load(sys.stdin)
  output = data['output']
  archive_file = data['archive_file']

  # Archive path should exist and be an absolute path to a file.
  assert os.path.isabs(archive_file), archive_file
  assert os.path.isfile(archive_file), archive_file

  # Output path should be an absolute path, and should NOT exist.
  assert os.path.isabs(output), output
  assert not os.path.exists(output), output

  file_type = 'zip' if archive_file.endswith('.zip') else 'tar'

  print 'Extracting %s (%s) -> %s ...' % (archive_file, file_type, output)
  try:
    os.makedirs(output)
    if file_type == 'zip':
      unzip(archive_file, output)
    else:
      untar(archive_file, output)
  except:
    shutil.rmtree(output, ignore_errors=True)
    raise
  return 0


if __name__ == '__main__':
  sys.exit(main())
