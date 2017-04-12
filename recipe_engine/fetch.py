# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import errno
import httplib
import json
import logging
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile


from cStringIO import StringIO
from collections import namedtuple

from . import package_pb2
from . import package_io
from . import util

# Add third party paths.
from . import env
from . import requests_ssl
from .requests_ssl import requests

import subprocess42
from google.protobuf import json_format

LOGGER = logging.getLogger(__name__)


class FetchError(Exception):
  pass


class FetchNotAllowedError(FetchError):
  pass


class UnresolvedRefspec(Exception):
  pass


# revision (str): the revision of this commit (i.e. hash)
# author_email (str|None): the email of the author of this commit
# message_lines (tuple(str)): the message of this commit
# spec (package_pb2.Package): the parsed infra/config/recipes.cfg file or None.
CommitMetadata = namedtuple('_CommitMetadata',
                            'revision author_email message_lines spec')


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
      package_pb2.DepSpec.GITILES: GitilesBackend,
    }[repo_type]

  def __init__(self, checkout_dir, repo_url, allow_network):
    """
    Args:
      checkout_dir (str): native absolute path to local directory that this
        Backend will manage.
      repo_url (str): url to remote repository that this Backend will connect
        to.
      allow_network (bool): Indicates that this Backend is permitted to make
        network operations.
    """
    self.checkout_dir = checkout_dir
    self.repo_url = repo_url

    self._allow_network = allow_network

  ### shared public implementations, do not override

  def assert_remote(self, opname):
    """This is a helper for Backend objects to use to check if network
    operations are allowed and raise FetchNotAllowedError if not.

    Example:
      self.assert_remote('fetch')
      self._do_real_fetch(...)

    Args:
      opname (str) - human-recognizable operation name for exception.
    """
    if not self._allow_network:
      raise FetchNotAllowedError('remote operation %r on %s' %
                                 (opname, self.repo_url,))


  # This is a simple mapping of
  #   repo_url -> git_revision -> commit_metadata()
  # It only holds cache entries for git commits (e.g. sha1 hashes)
  _GIT_METADATA_CACHE = {}

  # This matches git commit hashes.
  _COMMIT_RE = re.compile(r'^[a-fA-F0-9]{40}$')

  def commit_metadata(self, refspec):
    """Cached version of _commit_metadata_impl.

    The refspec will be resolved if it's not absolute.

    Returns {
      'author': '<author name>',
      'message': '<commit message>',
      'spec': package_pb2.Package or None,  # the parsed recipes.cfg file.
    }
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

  def updates(self, revision, other_revision, paths):
    """Returns a list of revisions between |revision| and |other_revision|.

    If |paths| is a non-empty list, the history is scoped just to these paths.

    Returns list(str) - The revisions in the range (revision,other_revision].
    """
    # TODO(iannucci): make this return list(CommitMetadata) instead.
    self.assert_resolved(revision)
    self.assert_resolved(other_revision)
    return self._updates_impl(revision, other_revision, paths)

  def get_more_recent_revision(self, revision, other_revision):
    """Returns the more recent of two revisions.

    Args:
      revision (str) - the first git commit
      other_revision (str) - the second git commit

    Returns (str) - either revision or other_revision
    """
    self.assert_resolved(revision)
    self.assert_resolved(other_revision)
    return self._get_more_recent_revision_impl(revision, other_revision)

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

  def _get_more_recent_revision_impl(self, revision, other_revision):
    """Returns the more recent of two revisions.

    Args:
      revision (str) - the first git commit
      other_revision (str) - the second git commit

    Returns (str) - either revision or other_revision
    """
    raise NotImplementedError()


  def _updates_impl(self, revision, other_revision, paths):
    """Returns a list of revisions between |revision| and |other_revision|.

    If |paths| is a non-empty list, the history is scoped just to these paths.

    Args:
      revision (str) - the first git commit
      other_revision (str) - the second git commit
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

  def _git(self, *args):
    """Runs a git command.

    Will automatically set low speed limit/time, and cd into the checkout_dir.

    Args:
      *args (str) - The list of command arguments to pass to git.

    Raises GitError on failure.
    """
    cmd = [
      self._GIT_BINARY,
      '-C', self.checkout_dir,
    ] + list(args)

    try:
      return self._execute(*cmd)
    except subprocess42.CalledProcessError as e:
      subcommand = (args[0]) if args else ('')
      raise GitError('Git "%s" failed: %s' % (subcommand, e.message,))

  def _execute(self, *args):
    """Runs a raw command. Separate so it's easily mockable."""
    LOGGER.info('Running: %s', args)
    return subprocess42.check_output(args)

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
        # us to switch between GitilesBackend and GitBackend.
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

    self.assert_remote('fetch')
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

  def _get_more_recent_revision_impl(self, revision, other_revision):
    return self._git(
      # Note three dots (...) here.
      'rev-list', '%s...%s' % (revision, other_revision),
    ).strip().splitlines()[0]

  def _updates_impl(self, revision, other_revision, paths):
    args = [
        'rev-list',
        '--reverse',
        '%s..%s' % (revision, other_revision),
    ]
    if paths:
      args.extend(['--'] + paths)
    return filter(bool, self._git(*args).strip().split('\n'))

  def _resolve_refspec_impl(self, revision):
    self._ensure_local_repo_exists()
    self.assert_remote('resolve refspec %r' % revision)
    rslt = self._git('ls-remote', self.repo_url, revision).split()[0]
    assert self.is_resolved_revision(rslt), repr(rslt)
    return rslt

  def _commit_metadata_impl(self, revision):
    self.assert_resolved(revision)

    # show
    #   %`author Email`
    #   %`Newline`
    #   %`Body`
    email_and_body = self._git(
      'show', '-s', '--format=%aE%n%B', revision).rstrip('\n').splitlines()

    try:
      spec = package_io.parse(self._git(
        'cat-file', 'blob', '%s:infra/config/recipes.cfg' % revision))
    except GitError:
      spec = None

    return CommitMetadata(revision, email_and_body[0],
                          tuple(email_and_body[1:]), spec)

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

  # Prefix at the beginning of Gerrit/Gitiles JSON API responses.
  _GERRIT_XSRF_HEADER = ')]}\'\n'

  @util.exponential_retry(condition=GitilesFetchError.transient)
  def _fetch_gitiles(self, url_fmt, *args):
    """Fetches a remote URL path and returns the response object on success.

    Args:
      url_fmt (str) - the url path fragment as a python %format string, like
        '%s/foo/bar?something=value'
      *args (str) - the arguments to format url_fmt with. They will be URL
        escaped.

    Returns requests.Response.
    """
    url = '%s/%s' % (self.repo_url,
                     url_fmt % tuple(map(requests.utils.quote, args)))
    LOGGER.info('fetching %s' % url)
    resp = requests.get(url)
    if resp.status_code != httplib.OK:
      raise GitilesFetchError(resp.status_code, resp.text)
    return resp

  def _fetch_gitiles_json(self, url_fmt, *args):
    """Fetches a remote URL path and expects a JSON object on success.

    Args:
      url_fmt (str) - the url path fragment as a python %format string, like
        '%s/foo/bar?something=value'
      *args (str) - the arguments to format url_fmt with. They will be URL
        escaped.

    Returns the decoded JSON object
    """
    resp = self._fetch_gitiles(url_fmt, *args)
    if not resp.text.startswith(self._GERRIT_XSRF_HEADER):
      raise GitilesFetchError(resp.status_code, 'Missing XSRF prefix')
    return json.loads(resp.text[len(self._GERRIT_XSRF_HEADER):])


  ### Backend implementations


  @property
  def repo_type(self):
    return package_pb2.DepSpec.GITILES

  def fetch(self, _refspec):
    # noop on Gitiles
    pass

  def checkout(self, refspec):
    requests_ssl.check_requests_ssl()
    LOGGER.info('Freshening repository %s in %s',
                self.repo_url, self.checkout_dir)

    shutil.rmtree(self.checkout_dir, ignore_errors=True)

    self.assert_remote('checkout')

    # Resolve the refspec if it's not a revision.
    revision = self.resolve_refspec(refspec)

    commit_metadata = self.commit_metadata(revision)
    package_spec = commit_metadata.spec
    recipes_path_rel = package_spec.recipes_path.encode('utf-8')

    # Re-create recipes.cfg in |checkout_dir| so that the repo's recipes.py
    # can look it up.
    recipes_cfg_path = os.path.join(self.checkout_dir,
                                    'infra', 'config', 'recipes.cfg')
    os.makedirs(os.path.dirname(recipes_cfg_path))
    package_io.PackageFile(recipes_cfg_path).write(package_spec)

    recipes_path = os.path.join(self.checkout_dir, recipes_path_rel)
    if not os.path.exists(recipes_path):
      os.makedirs(recipes_path)

    # TODO(iannucci): Implement parsing of 'bundle_extra_paths.txt' files so
    # that we can generate a bundle directly from gitiles without any local
    # state.

    # TODO(iannucci): This implementation may be slow if we need to retieve
    # multiple files/archives from the remote server. Should possibly consider
    # using a thread pool here.

    archive_response = self._fetch_gitiles(
      '+archive/%s/%s.tar.gz', revision, recipes_path_rel)
    with tarfile.open(fileobj=StringIO(archive_response.content)) as tf:
      tf.extractall(recipes_path)

  def _get_more_recent_revision_impl(self, revision, other_revision):
    # TODO(iannucci): implement or remove the need for this.
    #
    # This is used by the autoroller logic currently, which is forced to use
    # GitRepo's for all backends because this is not implemented.
    #
    # We could use gitiles apis (i.e. 'updates') to pre-fetch all commit
    # metadata and calculate roll candidates efficiently using those revision
    # lists. Doing that would eliminate the need to implement this method, and
    # would allow the autoroller to function without any persistent local state
    # (making it easier to administer an autoroller bot).
    raise NotImplementedError()

  def _updates_impl(self, revision, other_revision, paths):
    self.assert_remote('_updates_impl')

    # TODO(iannucci): implement paging

    # To include info about touched paths (tree_diff), pass name-status=1 below.
    log_json = self._fetch_gitiles_json(
      '+log/%s..%s?name-status=1&format=JSON', revision, other_revision)

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

    results.reverse()
    return results

  def _fetch_commit_json(self, refspec):
    return self._fetch_gitiles_json('+/%s?format=JSON', refspec)

  def _resolve_refspec_impl(self, refspec):
    if self.is_resolved_revision(refspec):
      return self.commit_metadata(refspec).commit
    return self._fetch_commit_json(refspec)['commit']

  def _commit_metadata_impl(self, revision):
    self.assert_remote('_commit_metadata_impl')
    rev_json = self._fetch_commit_json(revision)

    recipes_cfg_text = self._fetch_gitiles(
      '+/%s/infra/config/recipes.cfg?format=TEXT', revision
    ).text.decode('base64')
    spec = json_format.Parse(
      recipes_cfg_text, package_pb2.Package(), ignore_unknown_fields=True)

    return CommitMetadata(
      revision,
      rev_json['author']['email'],
      tuple(rev_json['message'].splitlines()),
      spec)
