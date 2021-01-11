#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Utility exporting basic filesystem operations.

This file was cut from "scripts/common/chromium_utils.py" at:
91310531c31fa645256b4fb5d44b460c42b3e151
"""

from __future__ import print_function

import argparse
import errno
import fnmatch
import glob2
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time


def _RmGlob(file_wildcard, root, include_hidden):
  """Removes files matching 'file_wildcard' in root and its subdirectories, if
  any exists.

  An exception is thrown if root doesn't exist."""
  wildcard = os.path.join(os.path.realpath(root), file_wildcard)
  for item in glob2.glob(wildcard, include_hidden=include_hidden):
    try:
      os.remove(item)
    except OSError, e:
      if e.errno != errno.ENOENT:
        raise


def _RmContents(path):
  if os.path.exists(path):
    os.chmod(path, 0770)
    for p in (os.path.join(path, x) for x in os.listdir(path)):
      if os.path.isdir(p):
        _RmTree(p)
      else:
        os.unlink(p)


def _RmTree(path):
  """Recursively removes a directory, even if it's marked read-only.

  Remove the directory located at path, if it exists.

  shutil.rmtree() doesn't work on Windows if any of the files or directories
  are read-only, which svn repositories and some .svn files are.  We need to
  be able to force the files to be writable (i.e., deletable) as we traverse
  the tree.

  Even with all this, Windows still sometimes fails to delete a file, citing
  a permission error (maybe something to do with antivirus scans or disk
  indexing).  The best suggestion any of the user forums had was to wait a
  bit and try again, so we do that too.  It's hand-waving, but sometimes it
  works. :/
  """
  if not os.path.exists(path):
    print('WARNING:  Failed to find %s during rmtree.  Ignoring.\n' % path)
    return

  if sys.platform == 'win32':
    # Give up and use cmd.exe's rd command.
    cmd = ['cmd.exe', '/c', 'rd', '/q', '/s', os.path.normcase(path)]
    for _ in xrange(3):
      print('RemoveDirectory running %s' % (' '.join(cmd)))
      if not subprocess.call(cmd):
        break
      print('  Failed')
      time.sleep(3)
    return

  # If we call "rmtree" on a file, just delete it.
  if not os.path.isdir(path):
    os.remove(path)
    return

  def RemoveWithRetry_non_win(rmfunc, path):
    if os.path.islink(path):
      return os.remove(path)
    return rmfunc(path)

  remove_with_retry = RemoveWithRetry_non_win

  def RmTreeOnError(function, path, excinfo):
    r"""This works around a problem whereby python 2.x on Windows has no ability
    to check for symbolic links.  os.path.islink always returns False.  But
    shutil.rmtree will fail if invoked on a symbolic link whose target was
    deleted before the link.  E.g., reproduce like this:
    > mkdir test
    > mkdir test\1
    > mklink /D test\current test\1
    > python -c "import chromium_utils; chromium_utils.RemoveDirectory('test')"
    To avoid this issue, we pass this error-handling function to rmtree.  If
    we see the exact sort of failure, we ignore it.  All other failures we re-
    raise.
    """

    exception_type = excinfo[0]
    exception_value = excinfo[1]
    # If shutil.rmtree encounters a symbolic link on Windows, os.listdir will
    # fail with a WindowsError exception with an ENOENT errno (i.e., file not
    # found).  We'll ignore that error.  Note that WindowsError is not defined
    # for non-Windows platforms, so we use OSError (of which it is a subclass)
    # to avoid lint complaints about an undefined global on non-Windows
    # platforms.
    if (function is os.listdir) and issubclass(exception_type, OSError):
      if exception_value.errno == errno.ENOENT:
        # File does not exist, and we're trying to delete, so we can ignore the
        # failure.
        print('WARNING:  Failed to list %s during rmtree.  Ignoring.\n' % path)
      else:
        raise
    else:
      raise

  for root, dirs, files in os.walk(path, topdown=False):
    # For POSIX:  making the directory writable guarantees removability.
    # Windows will ignore the non-read-only bits in the chmod value.
    os.chmod(root, 0770)
    for name in files:
      remove_with_retry(os.remove, os.path.join(root, name))
    for name in dirs:
      remove_with_retry(lambda p: shutil.rmtree(p, onerror=RmTreeOnError),
                        os.path.join(root, name))

  remove_with_retry(os.rmdir, path)


def _EnsureDir(mode, dest):
  if not os.path.isdir(dest):
    if os.path.exists(dest):
      raise OSError(errno.EEXIST, os.strerror(errno.EEXIST))
    os.makedirs(dest, mode)


def _Glob(base, pattern, include_hidden):
  base = os.path.realpath(base)
  hits = glob2.glob(os.path.join(base, pattern), include_hidden=include_hidden)
  if hits:
    print('\n'.join(sorted((os.path.relpath(hit, start=base) for hit in hits))))


def _ListDir(base, recursive):
  if recursive:
    out = []
    for dirpath, _, files in os.walk(base):
      out.extend(os.path.relpath(os.path.join(dirpath, f), base) for f in files)
  else:
    out = os.listdir(base)
  print('\n'.join(sorted(out)), end='')


def _Remove(path):
  try:
    os.remove(path)
  except OSError as e:
    if e.errno != errno.ENOENT:
      raise

def _Truncate(path, size_mb):
  with open(path, 'w') as f:
    f.truncate(size_mb * 1024 * 1024)


def _FlattenSingleDirectories(path):
  assert os.path.isabs(path), 'nonabs path: %r' % (path,)
  assert os.path.isdir(path), 'nondir path: %r' % (path,)

  first_single_dir = None
  print('flattening single directories in %r' % (path,))
  for root, dirs, files in os.walk(path):
    # if it's a single dir, we keep walking
    if len(dirs) == 1 and not files:
      if not first_single_dir:
        first_single_dir = os.path.join(path, dirs[0])
      continue

    # otherwise we found some stuff!
    if not first_single_dir:
      # if we didn't find a first_single_dir, we're still in the base directory
      # and don't have anything to do.
      print('contents appears already flattened')
      return 0

    print('found contents at: %r' % (os.path.relpath(root, path),))

    # first move the first_single_dir out of the way, in case there's
    # a file/folder we need to move that has a conflicting name.
    tmpname = tempfile.mktemp(dir=path)
    print('moving root folder out of the way: %r -> %r' % (first_single_dir, tmpname))
    os.rename(first_single_dir, tmpname)

    for name in itertools.chain(dirs, files):
      fullname = os.path.join(root, name).replace(first_single_dir, tmpname)
      to = os.path.join(path, name)
      print('mv %r %r' % (fullname, to))
      os.rename(fullname, to)
    print('moved %d dirs and %d files' % (len(dirs), len(files)))
    print('rm -rf %r' % (tmpname,))
    shutil.rmtree(tmpname)
    return 0

def _FileHash(sha, rel_path, base_path):
  path = os.path.join(base_path, rel_path)
  with open(path, 'rb') as f:
    sha.update(str(len(rel_path)))
    sha.update(rel_path)
    while True:
      f_stream = f.read(4096)
      if not f_stream:
        break
      sha.update(str(len(f_stream)))
      sha.update(f_stream)

def _ComputeHashPaths(base_path, *rel_paths):
  sha = hashlib.sha256()
  for rel_path in rel_paths:
    path = os.path.join(base_path, rel_path)
    if os.path.isfile(path):
      _FileHash(sha, rel_path, base_path)
    elif os.path.isdir(path):
      for root, dirs, files in os.walk(path, topdown=True):
        dirs.sort()  # ensure we walk dirs in sorted order
        files.sort()
        for f_name in files:
          rel_file_path = os.path.relpath(os.path.join(root, f_name), base_path)
          _FileHash(sha, rel_file_path, base_path)

  print(sha.hexdigest())
  return 0

def _CalculateHash(path):
  sha = hashlib.sha256()
  with open(path, 'rb') as f:
    while True:
      f_stream = f.read(4096)
      if not f_stream:
        break
      sha.update(f_stream)
  print(sha.hexdigest())
  return 0

def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('--json-output', required=True,
                      type=argparse.FileType('w'),
                      help="path to JSON output file")

  subparsers = parser.add_subparsers()

  # Subcommand: rmtree
  subparser = subparsers.add_parser('rmtree',
      help='Recursively remove a directory.')
  subparser.add_argument('source', help='A path to remove.')
  subparser.set_defaults(func=lambda opts: _RmTree(opts.source))

  # Subcommand: rmcontents
  subparser = subparsers.add_parser('rmcontents',
      help='Recursively remove the contents of a directory.')
  subparser.add_argument('source', help='The target directory.')
  subparser.set_defaults(func=lambda opts: _RmContents(opts.source))

  # Subcommand: rmwildcard
  subparser = subparsers.add_parser('rmglob',
      help='Recursively remove the contents of a directory.')
  subparser.add_argument('root', help='The directory to search through.')
  subparser.add_argument('wildcard', help='The wildcard expression to remove.')
  subparser.add_argument('--hidden', action='store_true',
                         help='Include hidden files.')
  subparser.set_defaults(func=lambda opts:
      _RmGlob(opts.wildcard, opts.root, opts.hidden))

  # Subcommand: copy
  subparser = subparsers.add_parser('copy',
      help='Copy one file to another. Behaves like shutil.copy().')
  subparser.add_argument('source', help='The file to copy.')
  subparser.add_argument('dest', help='The destination to copy to.')
  subparser.set_defaults(func=lambda opts: shutil.copy(opts.source, opts.dest))

  # Subcommand: copytree
  subparser = subparsers.add_parser('copytree',
      help='Recursively copy a file tree. Behaves like shutil.copytree().')
  subparser.add_argument('--symlinks', action='store_true',
                         help='Copy symlinks as symlinks.')
  subparser.add_argument('source', help='The directory to copy.')
  subparser.add_argument('dest', help='The destination directory to copy to.')
  subparser.set_defaults(
      func=lambda opts: shutil.copytree(opts.source, opts.dest, opts.symlinks))

  # Subcommand: move
  subparser = subparsers.add_parser('move',
      help='Moves/renames a file. Behaves like shutil.move().')
  subparser.add_argument('source', help='The item to move.')
  subparser.add_argument('dest', help='The destination name.')
  subparser.set_defaults(
      func=lambda opts: shutil.move(opts.source, opts.dest))

  # Subcommand: glob
  subparser = subparsers.add_parser('glob',
      help='Prints a list of absolute paths with match the pattern.')
  subparser.add_argument('base', help='The directory to glob in.')
  subparser.add_argument('pattern', help='The glob patern to expand.')
  subparser.add_argument('--hidden', action='store_true',
                         help='Include hidden files.')
  subparser.set_defaults(func=lambda opts:
      _Glob(opts.base, opts.pattern, opts.hidden))

  # Subcommand: remove
  subparser = subparsers.add_parser('remove',
      help='Remove a file')
  subparser.add_argument('source', help='The file to remove.')
  subparser.set_defaults(func=lambda opts: _Remove(opts.source))

  # Subcommand: listdir
  subparser = subparsers.add_parser('listdir',
      help='Print all entries in the given folder to stdout.')
  subparser.add_argument('source', help='The dir to list.')
  subparser.add_argument('--recursive', action='store_true',
                         help='Recurse into subdirectories.')
  subparser.set_defaults(
      func=lambda opts: _ListDir(opts.source, opts.recursive))

  # Subcommand: ensure-directory
  subparser = subparsers.add_parser('ensure-directory',
      help='Ensures that the given path is a directory.')
  subparser.add_argument('--mode', help='The octal mode of the directory.',
                         type=lambda s: int(s, 8))
  subparser.add_argument('dest', help='The dir to ensure.')
  subparser.set_defaults(func=lambda opts: _EnsureDir(opts.mode, opts.dest))

  # Subcommand: filesizes
  subparser = subparsers.add_parser('filesizes',
      help='Prints a list for sizes in bytes (1 per line) for each given file')
  subparser.add_argument('file', nargs='+', help='Path to a file')
  subparser.set_defaults(
      func=lambda opts: print('\n'.join(str(os.stat(f).st_size)
                                            for f in opts.file)))

  # Subcommand: filesizes
  subparser = subparsers.add_parser('symlink',
      help='Creates a symlink. Behaves like os.symlink.')
  subparser.add_argument('source', help='The thing to link to.')
  subparser.add_argument('link', help='The link to create.')
  subparser.set_defaults(
      func=lambda opts: os.symlink(opts.source, opts.link))

  # Subcommand: truncate
  subparser = subparsers.add_parser(
      'truncate', help='Creates an empty file with specified size.')
  subparser.add_argument('path', help='The path to the file.')
  subparser.add_argument('size_mb', help='The size of the file in megabytes.',
                         type=int)
  subparser.set_defaults(func=lambda opts: _Truncate(opts.path, opts.size_mb))

  # Subcommand: flatten_single_directories
  subparser = subparsers.add_parser(
      'flatten_single_directories',
      help=('Moves contents of single/dir/with/contents to the top level '
            'directory.'))
  subparser.add_argument('path', help='The path to flatten from.')
  subparser.set_defaults(func=lambda opts: _FlattenSingleDirectories(opts.path))

  # Subcommand: compute_hash
  subparser = subparsers.add_parser(
      'compute_hash',
      help='Computes hash of provided absolute directories and/or files.')
  subparser.add_argument('base_path', help='Base path to normalize all files.')
  subparser.add_argument('rel_paths', nargs='+',
                         help='List of relative paths of directories '
                              'and/or files.')
  subparser.set_defaults(func=lambda opts: _ComputeHashPaths(opts.base_path,
                                                             *opts.rel_paths))

  # Subcommand: file_hash
  subparser = subparsers.add_parser(
      'file_hash',
      help='Computes hash of a file in provided absolute path.')
  subparser.add_argument('file_path', help='Absolute path for the file.')
  subparser.set_defaults(func=lambda opts: _CalculateHash(opts.file_path))

  # Parse arguments.
  opts = parser.parse_args(args)

  # Actually do the thing.
  data = {
    'ok': False,
    'errno_name': '',
    'message': '',
  }
  try:
    opts.func(opts)
    data['ok'] = True
  except OSError as e:
    data['errno_name'] = errno.errorcode[e.errno]
    data['message'] = str(e)
  except shutil.Error as e:
    # Note that shutil.Error's "message" field can sometimes be a tuple, just
    # render the entire exception as a string to be safe.
    data['message'] = str(e)
  except Exception as e:
    data['message'] = 'UNKNOWN: %s' % e

  with opts.json_output:
    json.dump(data, opts.json_output)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
