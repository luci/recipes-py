# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import errno
import logging
import os
import re
import sys

from collections import namedtuple

from gevent import subprocess

from . import gitattr_checker
from . import simple_cfg
from .exceptions import GitFetchError, UnresolvedRefspec


LOGGER = logging.getLogger(__name__)


# revision (str): the revision of this commit (i.e. hash)
# author_email (str|None): the email of the author of this commit
# commit_timestamp (int): the unix commit timestamp for this commit
# message_lines (tuple(str)): the message of this commit
# spec (SimpleRecipesCfg): the parsed infra/config/recipes.cfg file or None.
# roll_candidate (bool): if this commit contains changes which are known to
#   affect the behavior of the recipes (i.e. modifications within recipe_path
#   and/or modifications to recipes.cfg)
CommitMetadata = namedtuple(
  '_CommitMetadata',
  'revision author_email commit_timestamp message_lines spec roll_candidate')


class Backend(object):
  def __init__(self, checkout_dir, repo_url):
    """
    Args:
      checkout_dir (str): native absolute path to local directory that this
        Backend will manage.
      repo_url (str|None): url to remote repository that this Backend will
        connect to. If None, then the repo will be assumed to exist at
        checkout_dir and all write operations will be disabled.
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
    key = self.repo_url
    if key is None:
      key = self.checkout_dir
    cache = self._GIT_METADATA_CACHE.setdefault(key, {})
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

  def fetch(self, refspec):
    """Does a fetch for the provided refspec (e.g. get all data from remote), if
    this backend supports it. Otherwise does nothing.

    Args:
      refspec (str) - a git refspec which is resolvable on the
        remote git repo, e.g. 'refs/heads/master', 'deadbeef...face', etc.
    """
    raise NotImplementedError()

  def checkout(self, refspec, revision=None):
    """Checks out given |repo| at |refspec| to |checkout_dir|.

    Args:
      refspec (str) - a git refspec which is resolvable on the
        remote git repo, e.g. 'refs/heads/master', etc. This will be used to
        fetch if the local git repo doesn't have `revision`.
      revision (str|None) - The git revision to checkout. If None, fetch will
        do an ls-remote operation to resolve `refspec` to its current revision.
    """
    # TODO(iannucci): Alter the contract for this method so that it only checks
    # out the files referred to according to the rules that the bundle
    # subcommand uses.
    raise NotImplementedError()

  def cat_file(self, revision, file_path):
    """Returns the bytes of the given |file_path| in |revision|.

    Args:
      revision (str) - The revision to cat the file from.
      file_path (str) - The git path for the file (from the root of the repo).

    Returns the file contents as a str.
    """
    raise NotImplementedError()

  def ls_files(self, *args):
    """Returns the stdout from `git ls-files *args` in this repo.

    Args:
      args (List[str]) - Additional arguments to pass to ls_files.

    Returns the stdout of the command.
    """
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


class GitBackend(Backend):
  """GitBackend uses a local git checkout."""

  if sys.platform.startswith(('win', 'cygwin')):
    GIT_BINARY = 'git.bat'
  else:
    GIT_BINARY = 'git'

  def __init__(self, *args, **kwargs):
    super(GitBackend, self).__init__(*args, **kwargs)
    self._did_ensure = False
    self._gitattr_checker = gitattr_checker.AttrChecker(self.checkout_dir)

  def _git(self, *args):
    """Runs a git command.

    Will automatically set low speed limit/time, and cd into the checkout_dir.

    Args:
      *args (str) - The list of command arguments to pass to git.

    Raises GitFetchError on failure.
    """
    if self.GIT_BINARY.endswith('.bat'):
      # On the esteemed Windows Operating System, '^' is an escape character.
      # Since .bat files are running cmd.exe under the hood, they interpret this
      # escape character. We need to ultimately get a single ^, so we need two
      # ^'s for when we invoke the .bat, and each of those needs to be escaped
      # when the bat ultimately invokes the git.exe binary. This leaves us with
      # a total of 4x the ^'s that we originally wanted. Hooray.
      args = [a.replace('^', '^^^^') for a in args]

    cmd = [
      self.GIT_BINARY,
      '-c', 'advice.detachedHead=false',  # to avoid spamming logs
      '-C', self.checkout_dir,
    ] + list(args)

    try:
      return self._execute(*cmd)
    except subprocess.CalledProcessError as e:
      raise GitFetchError('%r failed: %s: %s' % (cmd, e.message, e.output))

  def _execute(self, *args):
    """Runs a raw command. Separate so it's easily mockable."""
    LOGGER.info('Running: %s', args)

    process = subprocess.Popen(
      args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, stderr = process.communicate()
    retcode = process.poll()
    if retcode:
      if output and stderr:
        new_output = 'STDOUT\n%s\nSTDERR\n%s' % (output, stderr)
      else:
        new_output = output or stderr
      raise subprocess.CalledProcessError(
        retcode, args, new_output)
    return output

  def _ensure_local_repo_exists(self):
    """Ensures that self.checkout_dir is a valid git repository. Safe to call
    multiple times. If this is sucessful, the GitBackend will not try to
    re-initialize the checkout_dir again.

    Raises GitFetchError if it detected that checkout_dir is likely not a valid git
    repo.
    """
    if self._did_ensure:
      return
    if not os.path.isdir(os.path.join(self.checkout_dir, '.git')):
      try:
        # note that it's safe to re-init an existing git repo. This should allow
        # us to switch between GitBackend and other Backends.
        self._execute(self.GIT_BINARY, 'init', self.checkout_dir)
        self._did_ensure = True
      except subprocess.CalledProcessError as e:
        raise GitFetchError(False, 'Git "init" failed: '+e.message)

  def _has_rev(self, revision):
    """Returns True iff the on-disk repo has the given revision."""
    self.assert_resolved(revision)
    try:
      # use commit_metadata since it's cached and we're likely to call it
      # shortly after _has_rev anyway.
      self.commit_metadata(revision)
      return True
    except GitFetchError:
      return False


  ### Backend implementations

  def fetch(self, refspec):
    if self.repo_url is None:
      raise ValueError('cannot call GitBackend.fetch without a `repo_url`')
    self._ensure_local_repo_exists()

    args = ['fetch', self.repo_url]
    if not self.is_resolved_revision(refspec):
      args.append(refspec)

    LOGGER.info('fetching %s', self.repo_url)
    self._git(*args)

  def checkout(self, refspec, revision=None):
    if not revision:
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
    except GitFetchError:
      # At this point there are two possibilities:
      #   1) We have multiple processes attempting to manipulate this checkout.
      #      1a) They're trying to check out the same version (ok)
      #      2b) They're trying to check out different versions (undefined)
      #   2) This checkout had a killed manipulation attempt and index.lock is
      #      stale (we're the only process manipulating it now).
      #
      # In 1a and 2, removing the lockfile is correct. In 1b it means that
      # recipes.cfg is mutating while we're doing the fetch, so this is
      # definitely undefined-behavior territory.
      #
      # To unblock 1a and 2, removing the lockfile should be safe, though it may
      # result in other errors on Windows.
      #
      # In any event, it shouldn't make the situation worse.
      index_lock = os.path.join(self.checkout_dir, '.git', 'index.lock')
      try:
        os.remove(index_lock)
      except OSError as exc:
        if exc.errno != errno.EEXIST:
          LOGGER.warn('failed to remove %r, reset will fail: %s', index_lock, exc)
      self._git('reset', '-q', '--hard', revision)

  def cat_file(self, revision, file_path):
    self.assert_resolved(revision)
    return self._git('cat-file', 'blob', '%s:%s' % (revision, file_path))

  def ls_files(self, *args):
    return self._git('ls-files', *args)

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

  def _resolve_refspec_impl(self, refspec):
    self._ensure_local_repo_exists()
    # Can return e.g.
    #
    #   b4a1b1365895c5962fb3654aff61290be2a492ed	HEAD
    #   39bbb4e3749b0a9ebc6cb36d8b679b147e4ed270	refs/remotes/origin/HEAD
    #
    # So we need the 'splitlines' bit too.
    source = self.repo_url if self.repo_url is not None else '.'
    mapping = {
      ref: csum
      for csum, ref in (
        l.split()
        for l in self._git('ls-remote', source, refspec).splitlines()
      )
    }
    rslt = mapping[refspec]
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
      spec = simple_cfg.SimpleRecipesCfg.from_json_string(
        self.cat_file(revision, simple_cfg.RECIPES_CFG_LOCATION_REL))
    except GitFetchError:
      spec = None
    except ValueError:  # commit with unparsable recipes.cfg
      spec = None

    # check diff to see if it touches anything interesting.
    changed_files = set(self._git(
      'diff-tree', '-r', '--no-commit-id', '--name-only', '%s^!' % revision)
      .splitlines())

    recipes_path = spec.recipes_path if spec else ''

    has_interesting_changes = (
        simple_cfg.RECIPES_CFG_LOCATION_REL in changed_files or
        any(f.startswith(recipes_path) for f in changed_files) or
        any(f.split('/')[-1] == '.gitattributes' for f in changed_files) or
        self._gitattr_checker.check_files(revision, changed_files))

    return CommitMetadata(revision, meta[0],
                          int(meta[1]), tuple(meta[2:]),
                          spec, has_interesting_changes)
