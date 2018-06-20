# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import calendar
import httplib
import json
import logging
import os
import re
import shutil
import sys
import tarfile
import time

from cStringIO import StringIO
from collections import namedtuple

from . import package_pb2
from . import package_io
from . import util
from . import gitattr_checker

# Add third party paths.
from . import env
import requests

import subprocess42
from google.protobuf import json_format

LOGGER = logging.getLogger(__name__)


class FetchError(Exception):
  pass


class UnresolvedRefspec(Exception):
  pass


# revision (str): the revision of this commit (i.e. hash)
# author_email (str|None): the email of the author of this commit
# commit_timestamp (int): the unix commit timestamp for this commit
# message_lines (tuple(str)): the message of this commit
# spec (package_pb2.Package): the parsed infra/config/recipes.cfg file or None.
# roll_candidate (bool): if this commit contains changes which are known to
#   affect the behavior of the recipes (i.e. modifications within recipe_path
#   and/or modifications to recipes.cfg)
CommitMetadata = namedtuple(
  '_CommitMetadata',
  'revision author_email commit_timestamp message_lines spec roll_candidate')


class Backend(object):
  @staticmethod
  def class_for_type(repo_type):
    """
    Args:
      repo_type (package_pb2.DepSpec.RepoType)

    Returns Backend (class): Returns the Backend appropriate for the
      repo_type.
    """
    return {
      package_pb2.DepSpec.GIT:     GitBackend,
    }[repo_type]

  def __init__(self, checkout_dir, repo_url):
    """
    Args:
      checkout_dir (str): native absolute path to local directory that this
        Backend will manage.
      repo_url (str): url to remote repository that this Backend will connect
        to.
    """
    self.checkout_dir = checkout_dir
    self.repo_url = repo_url

  ### shared public implementations, do not override

  # This is a simple mapping of
  #   repo_url -> git_revision -> commit_metadata()
  # It only holds cache entries for git commits (e.g. sha1 hashes)
  _GIT_METADATA_CACHE = {}

  # This matches git commit hashes.
  _COMMIT_RE = re.compile(r'^[a-fA-F0-9]{40}$')

  def commit_metadata(self, refspec):
    """Cached version of _commit_metadata_impl.

    The refspec will be resolved if it's not absolute.

    Returns (CommitMetadata).
    """
    revision = self.resolve_refspec(refspec)
    cache = self._GIT_METADATA_CACHE.setdefault(self.repo_url, {})
    if revision not in cache:
      cache[revision] = self._commit_metadata_impl(revision)
    return cache[revision]

  @classmethod
  def is_resolved_revision(cls, revision):
    return cls._COMMIT_RE.match(revision)

  @classmethod
  def assert_resolved(cls, revision):
    if not cls.is_resolved_revision(revision):
      raise UnresolvedRefspec('unresolved refspec %r' % revision)

  def resolve_refspec(self, refspec):
    if self.is_resolved_revision(refspec):
      return refspec
    return self._resolve_refspec_impl(refspec)

  def updates(self, revision, other_revision):
    """Returns a list of revisions |revision| through |other_revision|
    (inclusive).

    Returns list(CommitMetadata) - The commit metadata in the range
      (revision,other_revision].
    """
    self.assert_resolved(revision)
    self.assert_resolved(other_revision)
    return self._updates_impl(revision, other_revision)

  ### direct overrides. These are public methods which must be overridden.

  @property
  def repo_type(self):
    """Returns package_pb2.DepSpec.RepoType."""
    raise NotImplementedError()

  def fetch(self, refspec):
    """Does a fetch for the provided refspec (e.g. get all data from remote), if
    this backend supports it. Otherwise does nothing.

    Args:
      refspec (str) - a git refspec which is resolvable on the
        remote git repo, e.g. 'refs/heads/master', 'deadbeef...face', etc.
    """
    raise NotImplementedError()

  def checkout(self, refspec):
    """Checks out given |repo| at |refspec| to |checkout_dir|.

    Args:
      refspec (str) - a git refspec which is resolvable on the
        remote git repo, e.g. 'refs/heads/master', 'deadbeef...face', etc.
    """
    # TODO(iannucci): Alter the contract for this method so that it only checks
    # out the files referred to according to the rules that the bundle
    # subcommand uses.
    raise NotImplementedError()

  ### private overrides. Override these in the implementations, but don't call
  ### externally.

  def _updates_impl(self, revision, other_revision):
    """Returns a list of revisions |revision| through |other_revision|. This
    includes |revision| and |other_revision|.

    Args:
      revision (str) - the first git commit
      other_revision (str) - the second git commit

    Returns list(CommitMetadata) - The commit metadata in the range
      [revision,other_revision].
    """
    raise NotImplementedError()

  def _resolve_refspec_impl(self, refspec):
    """Resolves the refspec to it's current REMOTE value.

    This must resolve to the remote value even when using a local clone (i.e.
    GitBackend).

    Args:
      refspec (str) - a git refspec which is resolvable on the
        remote git repo, e.g. 'refs/heads/master', 'deadbeef...face', etc.

    Returns (str) - The git commit for the given refspec.
    """
    raise NotImplementedError()

  def _commit_metadata_impl(self, revision):
    """Returns CommitMetadata for commit |revision|."""
    raise NotImplementedError()


class GitError(FetchError):
  pass


class GitBackend(Backend):
  """GitBackend uses a local git checkout."""

  if sys.platform.startswith(('win', 'cygwin')):
    _GIT_BINARY = 'git.bat'
  else:
    _GIT_BINARY = 'git'

  def __init__(self, *args, **kwargs):
    super(GitBackend, self).__init__(*args, **kwargs)
    self._did_ensure = False
    self._gitattr_checker = gitattr_checker.AttrChecker(self.checkout_dir)

  def _git(self, *args):
    """Runs a git command.

    Will automatically set low speed limit/time, and cd into the checkout_dir.

    Args:
      *args (str) - The list of command arguments to pass to git.

    Raises GitError on failure.
    """
    if self._GIT_BINARY.endswith('.bat'):
      # On the esteemed Windows Operating System, '^' is an escape character.
      # Since .bat files are running cmd.exe under the hood, they interpret this
      # escape character. We need to ultimately get a single ^, so we need two
      # ^'s for when we invoke the .bat, and each of those needs to be escaped
      # when the bat ultimately invokes the git.exe binary. This leaves us with
      # a total of 4x the ^'s that we originally wanted. Hooray.
      args = [a.replace('^', '^^^^') for a in args]

    cmd = [
      self._GIT_BINARY,
      '-C', self.checkout_dir,
    ] + list(args)

    try:
      return self._execute(*cmd)
    except subprocess42.CalledProcessError as e:
      raise GitError('%r failed: %s: %s' % (cmd, e.message, e.output))

  def _execute(self, *args):
    """Runs a raw command. Separate so it's easily mockable."""
    LOGGER.info('Running: %s', args)

    process = subprocess42.Popen(
      args, stdout=subprocess42.PIPE, stderr=subprocess42.PIPE)
    output, stderr = process.communicate()
    retcode = process.poll()
    if retcode:
      if output and stderr:
        new_output = 'STDOUT\n%s\nSTDERR\n%s' % (output, stderr)
      else:
        new_output = output or stderr
      raise subprocess42.CalledProcessError(
        retcode, args, new_output)
    return output

  def _ensure_local_repo_exists(self):
    """Ensures that self.checkout_dir is a valid git repository. Safe to call
    multiple times. If this is sucessful, the GitBackend will not try to
    re-initialize the checkout_dir again.

    Raises GitError if it detected that checkout_dir is likely not a valid git
    repo.
    """
    if self._did_ensure:
      return
    if not os.path.isdir(os.path.join(self.checkout_dir, '.git')):
      try:
        # note that it's safe to re-init an existing git repo. This should allow
        # us to switch between GitBackend and other Backends.
        self._execute(self._GIT_BINARY, 'init', self.checkout_dir)
        self._did_ensure = True
      except subprocess42.CalledProcessError as e:
        raise GitError(False, 'Git "init" failed: '+e.message)

  def _has_rev(self, revision):
    """Returns True iff the on-disk repo has the given revision."""
    self.assert_resolved(revision)
    try:
      # use commit_metadata since it's cached and we're likely to call it
      # shortly after _has_rev anyway.
      self.commit_metadata(revision)
      return True
    except GitError:
      return False


  ### Backend implementations


  @property
  def repo_type(self):
    return package_pb2.DepSpec.GIT

  def fetch(self, refspec):
    self._ensure_local_repo_exists()

    args = ['fetch', self.repo_url]
    if not self.is_resolved_revision(refspec):
      args.append(refspec)

    LOGGER.info('fetching %s', self.repo_url)
    self._git(*args)

  def checkout(self, refspec):
    revision = self.resolve_refspec(refspec)

    LOGGER.info('Checking out %r in %s (%s)',
                revision, self.checkout_dir, self.repo_url)
    self._ensure_local_repo_exists()

    if not self._has_rev(revision):
      self.fetch(refspec)

    # reset touches index.lock which is problematic when multiple processes are
    # accessing the recipes at the same time. To allieviate this, we do a quick
    # diff, which will exit if `revision` is not already checked out.
    try:
      self._git('diff', '--quiet', revision)
    except GitError:
      self._git('reset', '-q', '--hard', revision)

  def _updates_impl(self, revision, other_revision):
    args = [
        'rev-list',
        '--reverse',
        '--topo-order',
        '%s..%s' % (revision, other_revision),
    ]
    return [
      self.commit_metadata(rev)
      for rev in self._git(*args).strip().split('\n')
      if bool(rev)
    ]

  def _resolve_refspec_impl(self, revision):
    self._ensure_local_repo_exists()
    rslt = self._git('ls-remote', self.repo_url, revision).split()[0]
    assert self.is_resolved_revision(rslt), repr(rslt)
    return rslt

  def _commit_metadata_impl(self, revision):
    self.assert_resolved(revision)

    # show
    #   %`author Email`
    #   %`newline`
    #   %`commit time`
    #   %`newline`
    #   %`Body`
    meta = self._git(
      'show', '-s', '--format=%aE%n%ct%n%B', revision).rstrip('\n').splitlines()

    try:
      spec = package_io.parse(self._git(
        'cat-file', 'blob', '%s:%s' %
        (revision, package_io.InfraRepoConfig.RELPATH)))
    except GitError:
      spec = None

    # check diff to see if it touches anything interesting.
    changed_files = set(self._git(
      'diff-tree', '-r', '--no-commit-id', '--name-only', '%s^!' % revision)
      .splitlines())

    has_interesting_changes = (
        package_io.InfraRepoConfig.RELPATH in changed_files or
        any(f.startswith(spec.recipes_path) for f in changed_files) or
        any(self._gitattr_checker.check_file(revision, f)
            for f in changed_files))

    return CommitMetadata(revision, meta[0],
                          int(meta[1]), tuple(meta[2:]),
                          spec, has_interesting_changes)


def add_subparser(parser):
  helpstr = 'Fetch and update dependencies but take no other action.'

  fetch_p = parser.add_parser(
    'fetch', help=helpstr, description=helpstr)

  fetch_p.set_defaults(
    # fetch action is implied by recipes.py
    func=(lambda package_deps, engine_flags: 0))
