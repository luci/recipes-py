# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy

from future.utils import iteritems

from ..fetch import CommitMetadata

from recipe_engine.engine_types import freeze


class UnknownCommit(KeyError):
  pass


class BackwardsRoll(ValueError):
  pass


class CommitList(object):
  """A seekable list of CommitMetadata objects for a single repo.

  This can also be used to obtain the list of commits 'rolled so far' for the
  purposes of generating a changelist.
  """

  def __init__(self, url, branch, commit_list):
    """
    Args:
      commit_list (list(CommitMetadata)) - The list of CommitMetadata objects to
      use.
    """
    assert commit_list, 'commit_list is empty'
    assert all(isinstance(c, CommitMetadata) for c in commit_list)

    # This maps from commit hash -> index in _commits.
    rev_idx = {}
    # This maps dep_repo_name -> dep_commit -> set(idxs)
    dep_idx = {}

    revs_for_dep = {}
    for i, c in enumerate(commit_list):
      rev_idx[c.revision] = i

      for dep_repo_name, dep in iteritems(c.spec.deps):
        idx = dep_idx.setdefault(dep_repo_name, {})
        idx.setdefault(dep.revision, set()).add(i)
        revs_for_dep.setdefault(dep_repo_name, set()).add(i)

    # Record the commits that don't pin each dep, they are compatible with any
    # revision of the given dep
    for dep_repo_name, revs in iteritems(revs_for_dep):
      dep_idx[dep_repo_name][None] = set(range(len(commit_list))) - revs

    # Immutable state: safe to copy
    self.url = url
    self.branch = branch
    self._commits = tuple(commit_list)
    self._rev_idx = freeze(rev_idx)
    self._dep_idx = freeze(dep_idx)

  def __len__(self):
    return len(self._commits)

  @classmethod
  def from_backend(cls, dep, git_backend):
    """Returns a CommitList given the main repo's recipes.cfg and the repo
    itself.

    Args:
      * dep (SimpleRecipeDep) - The dependency description that we want to
        analyze for updates. The commit list will contain everything between
        `dep.revision` and the current fetch target for the sdep.
      * git_backend (fetch.GitBackend) - The repo to get a CommitList from.

    Returns CommitList
    """
    return CommitList(
        git_backend.repo_url,
        dep.branch,
        ([git_backend.commit_metadata(dep.revision)] + git_backend.updates(
            dep.revision, git_backend.resolve_refspec(dep.branch))),
    )

  class _Cursor(object):

    def __init__(self, commit_list):
      self._commit_list = commit_list
      self._cur_idx = 0

    @property
    def current(self):
      """Gets the current CommitMetadata.

      Returns CommitMetadata or None if there is no current commit.
      """
      if self._cur_idx >= len(self._commit_list):
        return None
      return self._commit_list._commits[self._cur_idx]

    @property
    def next_roll_candidate(self):
      """Gets the next CommitMetadata with roll_candidate==True
      without advancing the current index.

      Returns:
        The CommitMetadata of the next roll candidate, or None if there
        is no next roll candidate.
      """
      for commit in self._commit_list._commits[self._cur_idx + 1:]:
        if commit.roll_candidate:
          return commit
      return None

    def advance_to(self, revision):
      """Advances the current position to == revision.

      Args:
        revision (str) - The revision to advance to.

      Returns:
        The new current CommitMetadata.

      Raises:
        UnknownCommit if revision is not in the commit list.
        BackwardsRoll if revision preces the current revision.
      """
      idx = self._commit_list._idx_of(revision)
      if idx < self._cur_idx:
        raise BackwardsRoll(revision)
      self._cur_idx = idx

  def cursor(self):
    """Returns a cursor for maintaining a position within the commits.
    """
    return self._Cursor(self)

  def dist(self, revision1, revision2=None):
    """Compute the distance to a revision.

    The function can be called with one or two revisions. If called with
    1 revision, it will be the "to" revision and the first revision in
    the commit list will be the "from" revision. If called with 2
    revisions, the "to" revision will be the second revision and the
    "from" revision will be the first revision.

    Returns:
      The number of revisions that the "to" revision is ahead of the
      "from" revision. If the "to" revision is not ahead of the "from"
      revision, None will be returned. If the "to" revision is not
      present in the commit list, it is assumed to precede the first
      revision in the commit list and None will be returned.

    Raises:
      UnknownCommit if the "from" revision is not present in the commit
      list.
    """
    if revision2 is None:
      to_revision = revision1
      from_idx = 0
    else:
      to_revision = revision2
      from_idx = self._idx_of(revision1)
    try:
      to_idx = self._idx_of(to_revision)
    except UnknownCommit:
      return None
    dist = to_idx - from_idx
    if dist < 0:
      return None
    return dist

  def _idx_of(self, revision):
    idx = self._rev_idx.get(revision)
    if idx is None:
      raise UnknownCommit(revision)
    return idx

  def lookup(self, revision):
    """Finds a CommitMetadata given its commit id.

    Returns: CommitMetadata
    Raises:
      UnknownCommit - if revision is not found.
    """
    return self._commits[self._idx_of(revision)]

  def _compatible_indexes(self, config, limited_to=None):
    """Finds the indexes of commits that are compatible with the config.

    Args:
      config (mapping(str, str)) - The pins to check against for
        compatibility.
      limited_to (iterable(int)) - Indexes to limit the check to. If not
        provided, all indexes in the commit list will be considered.

    Returns:
      The set of indexes of commits that are compatible with the
      provided config. A commit is compatible with the provided config
      if for each repo present in config, the commit either does not
      have a dep on the repo or the dep's revision value is equal to the
      config's revison.
    """
    compatible_indexes = set(limited_to or range(len(self._commits)))
    for repo_name, revision in iteritems(config):
      idx_table = self._dep_idx.get(repo_name)
      if not idx_table:
        continue

      # idx_table.get(None, set()) is the indexes of commits that do not have a
      # dependency on the repo in question, so they are compatible with any
      # revision
      compatible_indexes &= (
          idx_table.get(revision, set()) | idx_table.get(None, set()))
      if not compatible_indexes:
        break

    return compatible_indexes

  def is_compatible(self, revision, config):
    """Returns whether or not a revision is compatible with the config.

    Args:
      revision (str) - The revision within this commit list to check.
      config (mapping(str, str)) - The pins to check against for
        compatibility.

    Returns bool - Whether the repositories in common between config and
      the dependencies of the commit with revision have the same
      associated revisions.
    """
    compatible_indexes = self._compatible_indexes(config,
                                                  [self._idx_of(revision)])
    return bool(compatible_indexes)

  def compatible_commits(self, config):
    """Returns the revisions that are compatible with the config.

    Args:
      config (mapping(str, str)) - The pins to check against for
        compatibility.

    Returns list(CommitMetadata) - The commits where the repositories in
      common between config and the dependencies of the commits have the
      same revisions.
    """
    return [self._commits[i] for i in self._compatible_indexes(config)]

  def changelist(self, revision):
    """Returns a list of all CommitMetadata from the beginning of this
    CommitList up to and including the provided revision.

    Args:
      target_commit (str) - the revision to obtain the changelist for.

    Returns list(CommitMetadata) - The CommitMetadata objects corresponding to
      the provided target_commit.

    Raises:
      UnknownCommit if target_commit is not found.
    """
    return list(self._commits[:self._idx_of(revision) + 1])
