# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIRD_PARTY = os.path.join(BASE_DIR, 'recipe_engine', 'third_party')
sys.path.insert(0, os.path.join(THIRD_PARTY, 'requests'))

import requests

from .third_party import subprocess42
from .third_party.google.protobuf import text_format

from . import package_pb2


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


class Backend(object):
  def checkout(self, repo, revision, checkout_dir, allow_fetch):
    """Checks out given |repo| at |revision| to |checkout_dir|.

    Network operations are performed only if |allow_fetch| is True.
    """
    raise NotImplementedError()


class GitBackend(Backend):
  """GitBackend uses a local git checkout."""

  def checkout(self, repo, revision, checkout_dir, allow_fetch):
    logging.info('Freshening repository %s in %s', repo, checkout_dir)

    if not os.path.isdir(checkout_dir):
      if not allow_fetch:
        raise FetchNotAllowedError(
            'need to clone %s but fetch not allowed' % repo)
      _run_git(None, 'clone', '-q', repo, checkout_dir)
    elif not os.path.isdir(os.path.join(checkout_dir, '.git')):
      raise UncleanFilesystemError(
          '%s exists but is not a git repo' % checkout_dir)

    actual_origin = _run_git(
        checkout_dir, 'config', 'remote.origin.url').strip()
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


class GitilesBackend(Backend):
  """GitilesBackend uses a repo served by Gitiles."""

  def checkout(self, repo, revision, checkout_dir, allow_fetch):
    logging.info('Freshening repository %s in %s', repo, checkout_dir)

    # TODO(phajdan.jr): implement caching.
    if not allow_fetch:
      raise FetchNotAllowedError(
          'need to download %s from gitiles but fetch not allowed' % repo)

    rev_url = '%s/+/%s?format=JSON' % (repo, requests.utils.quote(revision))
    logging.info('fetching %s', rev_url)
    rev_raw = requests.get(rev_url).text
    if not rev_raw.startswith(')]}\'\n'):
      raise FetchError('Unexpected gitiles response: %s' % rev_raw)
    rev_json = json.loads(rev_raw.split('\n', 1)[1])
    orig_revision = revision
    revision = rev_json['commit']
    logging.info('resolved %s to %s', orig_revision, revision)

    shutil.rmtree(checkout_dir, ignore_errors=True)

    recipes_cfg_url = '%s/+/%s/infra/config/recipes.cfg?format=TEXT' % (
        repo, requests.utils.quote(revision))
    logging.info('fetching %s' % recipes_cfg_url)
    recipes_cfg_request = requests.get(recipes_cfg_url)
    recipes_cfg_text = base64.b64decode(recipes_cfg_request.text)
    recipes_cfg_proto = package_pb2.Package()
    text_format.Merge(recipes_cfg_text, recipes_cfg_proto)
    recipes_path_rel = recipes_cfg_proto.recipes_path

    # Re-create recipes.cfg in |checkout_dir| so that the repo's recipes.py
    # can look it up.
    recipes_cfg_path = os.path.join(
        checkout_dir, 'infra', 'config', 'recipes.cfg')
    os.makedirs(os.path.dirname(recipes_cfg_path))
    with open(recipes_cfg_path, 'w') as f:
      f.write(recipes_cfg_text)

    recipes_path = os.path.join(checkout_dir, recipes_path_rel)
    os.makedirs(recipes_path)

    archive_url = '%s/+archive/%s/%s.tar.gz' % (
        repo, requests.utils.quote(revision), recipes_path_rel)
    logging.info('fetching %s' % archive_url)
    archive_request = requests.get(archive_url)
    with tempfile.NamedTemporaryFile() as f:
      f.write(archive_request.content)
      f.flush()
      with tarfile.open(f.name) as archive_tarfile:
        archive_tarfile.extractall(recipes_path)
