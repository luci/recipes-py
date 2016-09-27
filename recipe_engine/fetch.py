# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
import functools
import httplib
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import time

# Add third party paths.
from . import env
from . import requests_ssl
from . import util
from .requests_ssl import requests

import subprocess42
from google.protobuf import text_format

from . import package_pb2


class FetchError(Exception):
  pass


class FetchNotAllowedError(FetchError):
  pass


class Backend(object):
  @property
  def repo_type(self):
    """Returns repo type (see package_pb2.DepSpec)."""
    raise NotImplementedError()

  @staticmethod
  def branch_spec(branch):
    """Returns branch spec for given branch suitable for given git backend."""
    raise NotImplementedError()

  def checkout(self, repo, revision, checkout_dir, allow_fetch):
    """Checks out given |repo| at |revision| to |checkout_dir|.

    Network operations are performed only if |allow_fetch| is True.
    """
    raise NotImplementedError()

  def updates(self, repo, revision, checkout_dir, allow_fetch,
              other_revision, paths):
    """Returns a list of revisions between |revision| and |other_revision|.

    Network operations are performed only if |allow_fetch| is True.

    If |paths| is a non-empty list, the history is scoped just to these paths.
    """
    raise NotImplementedError()

  def commit_metadata(self, repo, revision, checkout_dir, allow_fetch):
    """Returns a dictionary of metadata about commit |revision|.

    The dictionary contains the following keys: author, message.
    """
    raise NotImplementedError()


class UncleanFilesystemError(FetchError):
  pass


class GitError(FetchError):

  def __init__(self, is_remote, message):
    super(GitError, self).__init__(message)
    self.is_remote = is_remote

  @staticmethod
  def is_remote_error(e):
    return isinstance(e, GitError) and e.is_remote


class GitBackend(Backend):
  """GitBackend uses a local git checkout."""

  class Git(object):

    # The set of Git subcommands that are considered network-touching
    # subcommands and, therefore, subject to flake and retriable.
    _REMOTE_SUBCOMMANDS = {'clone', 'fetch'}

    def __init__(self, checkout_dir=None):
      self._checkout_dir = checkout_dir

    @staticmethod
    def _resolve_git():
      """Resolves the Git command to run based on current platform."""
      return 'git.bat' if sys.platform.startswith(('win', 'cygwin')) else 'git'

    def __call__(self, *args):
      cmd = [self._resolve_git()]
      if self._checkout_dir is not None:
        cmd += ['-C', self._checkout_dir]
      cmd += list(args)

      try:
        return self._execute(*cmd)
      except subprocess42.CalledProcessError as e:
        subcommand = (args[0]) if args else ('')
        is_remote = subcommand in self._REMOTE_SUBCOMMANDS
        raise GitError(is_remote, 'Git "%s" failed: %s' % (
            subcommand, e.message,))

    def _execute(self, *args):
      """Runs a raw command. Separate so it's easily mockable."""
      logging.info('Running: %s', args)
      return subprocess42.check_output(args)


  @property
  def repo_type(self):
    return package_pb2.DepSpec.GIT

  @staticmethod
  def branch_spec(branch):
    return 'origin/%s' % branch

  @util.exponential_retry(condition=GitError.is_remote_error)
  def checkout(self, repo, revision, checkout_dir, allow_fetch):
    logging.info('Freshening repository %s in %s', repo, checkout_dir)

    git = self.Git()
    if not os.path.isdir(checkout_dir):
      if not allow_fetch:
        raise FetchNotAllowedError(
            'need to clone %s but fetch not allowed' % repo)
      git('clone', '-q', repo, checkout_dir)
    elif not os.path.isdir(os.path.join(checkout_dir, '.git')):
      raise UncleanFilesystemError(
          '%s exists but is not a git repo' % checkout_dir)

    git = self.Git(checkout_dir=checkout_dir)
    git('config', 'remote.origin.url', repo)
    try:
      git('rev-parse', '-q', '--verify', '%s^{commit}' % revision)
    except GitError as e:
      logging.warning('Revision %s is not available: %s', revision, e)

      # Revision does not exist. If we can't fetch, then we fail here.
      if not allow_fetch:
        raise FetchNotAllowedError(
            'need to fetch %s but fetch not allowed' % repo)
      git('fetch')

    git('reset', '-q', '--hard', revision)

  @util.exponential_retry(condition=GitError.is_remote_error)
  def updates(self, repo, revision, checkout_dir, allow_fetch,
              other_revision, paths):
    self.checkout(repo, revision, checkout_dir, allow_fetch)

    git = self.Git(checkout_dir=checkout_dir)
    if allow_fetch:
      git('fetch')

    args = [
        'rev-list',
        '--reverse',
        '%s..%s' % (revision, other_revision),
    ]
    if paths:
      args.extend(['--'] + paths)
    return filter(bool, git(*args).strip().split('\n'))

  def commit_metadata(self, repo, revision, checkout_dir, allow_fetch):
    git = self.Git(checkout_dir=checkout_dir)
    return {
      'author': git('show', '-s', '--pretty=%aE', revision).strip(),
      'message': git('show', '-s', '--pretty=%B', revision).strip(),
    }


class GitilesFetchError(FetchError):
  """An HTTP error that occurred during Gitiles fetching."""

  def __init__(self, status, message):
    super(GitilesFetchError, self).__init__(
        'Gitiles error code (%d): %s' % (status, message))
    self.status = status
    self.message = message

  @staticmethod
  def transient(e):
    """
    Returns (bool): True if "e" is a GitilesFetchError with transient HTTP code.
    """
    return (isinstance(e, GitilesFetchError) and
            e.status >= httplib.INTERNAL_SERVER_ERROR)


class GitilesBackend(Backend):
  """GitilesBackend uses a repo served by Gitiles."""

  # Header at the beginning of Gerrit/Gitiles JSON API responses.
  _GERRIT_XSRF_HEADER = ')]}\'\n'

  @property
  def repo_type(self):
    return package_pb2.DepSpec.GITILES

  @staticmethod
  def branch_spec(branch):
    return branch

  def checkout(self, repo, revision, checkout_dir, allow_fetch):
    requests_ssl.check_requests_ssl()
    logging.info('Freshening repository %s in %s', repo, checkout_dir)

    # TODO(phajdan.jr): implement caching.
    if not allow_fetch:
      raise FetchNotAllowedError(
          'need to download %s from gitiles but fetch not allowed' % repo)

    revision = self._resolve_revision(repo, revision)

    shutil.rmtree(checkout_dir, ignore_errors=True)

    recipes_cfg_url = '%s/+/%s/infra/config/recipes.cfg?format=TEXT' % (
        repo, requests.utils.quote(revision))
    recipes_cfg_text = base64.b64decode(
        self._fetch_gitiles(recipes_cfg_url).text)
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
    if not os.path.exists(recipes_path):
      os.makedirs(recipes_path)

    archive_url = '%s/+archive/%s/%s.tar.gz' % (
        repo, requests.utils.quote(revision), recipes_path_rel)
    archive_response = self._fetch_gitiles(archive_url)
    with tempfile.NamedTemporaryFile(delete=False) as f:
      f.write(archive_response.content)
      f.close()

      try:
        with tarfile.open(f.name) as archive_tarfile:
          archive_tarfile.extractall(recipes_path)
      finally:
        os.unlink(f.name)

  def updates(self, repo, revision, checkout_dir, allow_fetch,
              other_revision, paths):
    if not allow_fetch:
      raise FetchNotAllowedError(
          'requested updates for %s from gitiles but fetch not allowed' % repo)

    revision = self._resolve_revision(repo, revision)
    other_revision = self._resolve_revision(repo, other_revision)
    # To include info about touched paths (tree_diff), pass name-status=1 below.
    log_json = self._fetch_gitiles_json(
        '%s/+log/%s..%s?name-status=1&format=JSON' % (
            repo, revision, other_revision))

    results = []
    for entry in log_json['log']:
      matched = False
      for path in paths:
        for diff_entry in entry['tree_diff']:
          if (diff_entry['old_path'].startswith(path) or
              diff_entry['new_path'].startswith(path)):
            matched = True
            break
        if matched:
          break
      if matched or not paths:
        results.append(entry['commit'])

    return list(reversed(results))

  def commit_metadata(self, repo, revision, checkout_dir, allow_fetch):
    if not allow_fetch:
      raise FetchNotAllowedError(
          ('requested commit metadata for %s (%s)from gitiles but fetch not '
           'allowed') % (repo, revision))
    rev_json = self._revision_metadata(repo, revision)
    return {
      'author': rev_json['author']['email'],
      'message': rev_json['message'],
    }

  def _revision_metadata(self, repo, revision):
    """Returns JSON metadata (in Gitiles format) for given revision."""
    return self._fetch_gitiles_json(
        '%s/+/%s?format=JSON' % (repo, requests.utils.quote(revision)))

  def _resolve_revision(self, repo, revision):
    """Returns a git sha corresponding to given revision.

    Examples of non-sha revision: origin/master, HEAD."""
    rev_json = self._revision_metadata(repo, revision)
    logging.info('resolved %s to %s', revision, rev_json['commit'])
    return rev_json['commit']

  @staticmethod
  @util.exponential_retry(condition=GitilesFetchError.transient)
  def _fetch_gitiles(url):
    """Fetches a remote URL and returns the response object on success."""
    logging.info('fetching %s' % url)
    resp = requests.get(url)
    if resp.status_code != httplib.OK:
      raise GitilesFetchError(resp.status_code, resp.text)
    return resp

  @classmethod
  @util.exponential_retry(condition=GitilesFetchError.transient)
  def _fetch_gitiles_json(cls, url):
    """Fetches JSON from Gitiles and returns parsed result."""
    logging.info('fetching %s', url)

    resp = requests.get(url)
    if resp.status_code != httplib.OK:
      raise GitilesFetchError(resp.status_code, resp.text)

    if not resp.text.startswith(cls._GERRIT_XSRF_HEADER):
      raise GitilesFetchError(resp.status_code, 'Missing XSRF header')

    return json.loads(resp.text[len(cls._GERRIT_XSRF_HEADER):])
