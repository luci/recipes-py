# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import sys

from .third_party import subprocess42


class FetchError(Exception):
  pass


class UncleanFilesystemError(FetchError):
  pass


class FetchNotAllowedError(FetchError):
  pass


def _run_git(checkout_dir, *args):
  if sys.platform.startswith(('win', 'cygwin')):
    cmd = ['git.bat']
  else:
    cmd = ['git']

  if checkout_dir is not None:
    cmd += ['-C', checkout_dir]
  cmd += list(args)

  logging.info('Running: %s', cmd)
  return subprocess42.check_output(cmd)


def ensure_git_checkout(repo, revision, checkout_dir, allow_fetch):
  """Fetches given |repo| at |revision| to |checkout_dir| using git.

  Network operations are performed only if |allow_fetch| is True.
  """
  logging.info('Freshening repository %s in %s', repo, checkout_dir)

  if not os.path.isdir(checkout_dir):
    if not allow_fetch:
      raise FetchNotAllowedError(
          'need to clone %s but fetch not allowed' % repo)
    _run_git(None, 'clone', '-q', repo, checkout_dir)
  elif not os.path.isdir(os.path.join(checkout_dir, '.git')):
    raise UncleanFilesystemError(
        '%s exists but is not a git repo' % checkout_dir)

  actual_origin = _run_git(checkout_dir, 'config', 'remote.origin.url').strip()
  if actual_origin != repo:
    raise UncleanFilesystemError(
        ('workdir %r exists but uses a different origin url %r '
         'than requested %r') % (checkout_dir, actual_origin, repo))

  try:
    _run_git(checkout_dir, 'rev-parse', '-q', '--verify',
             '%s^{commit}' % revision)
  except subprocess42.CalledProcessError:
    if not allow_fetch:
      raise FetchNotAllowedError(
          'need to fetch %s but fetch not allowed' % repo)
    _run_git(checkout_dir, 'fetch')
  _run_git(checkout_dir, 'reset', '-q', '--hard', revision)
