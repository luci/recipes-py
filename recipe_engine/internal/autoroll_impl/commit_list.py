# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from ..fetch import CommitMetadata

class UnknownCommit(KeyError):
  pass

class CommitList(object):
  """A seekable list of CommitMetadata objects for a single repo.

  This can also be used to obtain the list of commits 'rolled so far' for the
  purposes of generating a changelist.
  """

  def __init__(self, commit_list):
    """
    Args:
      commit_list (list(CommitMetadata)) - The list of CommitMetadata objects to
      use.
    """
    assert commit_list, 'commit_list is empty'
    assert all(isinstance(c, CommitMetadata) for c in commit_list)
    self._commits = list(commit_list)
    self._cur_idx = 0
    self._next_roll_candidate_idx = None

    # This maps from commit hash -> index in _commits.
    self._rev_idx = {}

    # This maps dep_repo_name -> dep_commit -> set(idxs)
    self._dep_idx = {}
    for i, c in enumerate(commit_list):
      self._rev_idx[c.revision] = i

      for dep_repo_name, dep in c.spec.deps.iteritems():
        idx = self._dep_idx.setdefault(dep_repo_name, {})
        idx.setdefault(dep.revision, set()).add(i)

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
      [git_backend.commit_metadata(dep.revision)] +
      git_backend.updates(dep.revision, git_backend.resolve_refspec(dep.branch))
    )

  @property
  def current(self):
    """Gets the current CommitMetadata.

    Returns CommitMetadata or None if there is no current commit.
    """
    if self._cur_idx >= len(self._commits):
      return None
    return self._commits[self._cur_idx]

  @property
  def next(self):
    """Gets the next CommitMetadata without advancing the current index.

    Returns the next CommitMetadata or None, if there is no next CommitMetadata.
    """
    nxt_idx = self._cur_idx+1
    if nxt_idx >= len(self._commits):
      return None
    return self._commits[nxt_idx]

  @property
  def next_roll_candidate(self):
    """Gets the next CommitMetadata and distance with roll_candidate==True
    without advancing the current index.

    Returns (CommitMetadata, <distance>), or (None, None) if there is no next
      roll_candidate.
    """
    # Compute and cache the next roll candidate index.
    nxt_idx = self._next_roll_candidate_idx
    if nxt_idx is None or nxt_idx <= self._cur_idx:
      nxt_idx = None
      for i, commit in enumerate(self._commits[self._cur_idx+1:]):
        if commit.roll_candidate:
          nxt_idx = self._cur_idx + i + 1
          break
      self._next_roll_candidate_idx = nxt_idx

    if nxt_idx is not None:
      return self._commits[nxt_idx], nxt_idx - self._cur_idx
    return (None, None)

  def advance(self):
    """Advances the current CommitMetadata by one.

    That is: CommitList.next becomes CommitList.current.

    Returns the now-current CommitMetadata (or None, if there was no next
      CommitMetadata).
    """
    ret = self.next
    if ret:
      self._cur_idx += 1
    return ret

  def _idx_of(self, commit):
    idx = self._rev_idx.get(commit)
    if idx is None:
      raise UnknownCommit(commit)
    return idx

  def lookup(self, commit):
    """Finds a CommitMetadata given its commit id.

    Returns: CommitMetadata
    Raises:
      UnknownCommit - if commit is not found.
    """
    return self._commits[self._idx_of(commit)]

  def dist_to(self, target_commit):
    """Returns the number of commits between the current CommitMetadata's commit
    and the target_commit.

    Args:
      target_commit (str) - the commit to determine the distance for.

    Returns int: The number of revisions between the current commit and
      target_commit. If target_commit == current.revision, then this will be 0.
      If target_commit preceeds current.revision, this will be negative.
      Otherwise this will be positive.

      If target_commit is not found, this returns 1 past the end of the
      CommitList.
    """
    try:
      return self._idx_of(target_commit) - self._cur_idx
    except UnknownCommit:
      return len(self._commits) - self._cur_idx

  def dist_compatible_with(self, dep_repo_name, dep_commit):
    """Returns the number of commits between the current CommitMetadata's commit
    and the next commit which would be compatible with the given
    (dep_repo_name, dep_commit). This will essentially search through all the
    known future commits in this CommitList and find the closest one that
    depends on dep_repo_name@dep_commit, and return the distance to that.

    If no commits from this repo depend on dep_repo_name, this returns 0. If
    this repo depends on dep_repo_name, but no compatibility with dep_commit is
    found, this returns len(#commits_to_HEAD).

    Args:
      dep_repo_name (str) - The repo_name that this repo possibly depends on.
      dep_commit (str) - The commit value for the dependency to search for.

    Returns int: The number of revisions between the current commit and the
      nearest future commit which depends on dep_repo_name@dep_commit. May be 0
      if the current commit is compatible with the dependency already.
    """
    idx_table = self._dep_idx.get(dep_repo_name)
    if not idx_table:
      return 0

    if dep_commit not in idx_table:
      # If it's not in idx_table, assume that it's past the end of the currently
      # available revisions.
      return len(self._commits) - self._cur_idx

    # only consider at same-or-future indicies
    return max(
      0,
      (
        # We filter out indexes which are less than the current index to
        # avoid issues during reverts.
        min(i for i in idx_table[dep_commit] if i >= self._cur_idx)
        - self._cur_idx
      )
    )

  def advance_to(self, target_commit):
    """Advances the current position to == target_commit.

    Args:
      target_commit (str) - the commit to determine the distance for.

    Returns the new current CommitMetadata, or None if it couldn't be advanced.
    """
    dist = self.dist_to(target_commit)
    if dist == len(self._commits) - self._cur_idx or dist < 0:
      return None
    if dist > 0:
      self._cur_idx += dist
    return self.current

  def changelist(self, target_commit):
    """Returns a list of all CommitMetadata from the beginning of this
    CommitList up to and including the provided commit.

    Args:
      target_commit (str) - the commit to obtain the changelist for.

    Returns list(CommitMetadata) - The CommitMetadata objects corresponding to
      the provided target_commit.

    Raises:
      UnknownCommit if target_commit is not found.
    """
    return list(self._commits[:self._idx_of(target_commit)+1])
