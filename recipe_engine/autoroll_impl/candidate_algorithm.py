# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys
import time

from recipe_engine import package

from .commit_list import CommitList
from .roll_candidate import RollCandidate


def get_commitlists(deps):
  """Returns {'project_id': CommitList} for every repo this recipe repo depends
  on.

  Args:
    context (PackageContext) - The local context for where the repos live, etc.
    deps (dict(project_id, RepoSpec)) - The dependencies to grab.

  Returns dict(project_id, CommitList) where each project_id is one of the repos
    mentioned in the deps.
  """
  return {
    project_id: CommitList.from_repo_spec(repo_spec)
    for project_id, repo_spec in deps.iteritems()
  }


def find_best_rev(repos):
  """Returns the project_id of the best repo to roll.

  "Best" is determined by "is an interesting commit and moves the least amount
  of commits, globally".

  "Interesting" means "the commit modifies one or more recipe related files",
  and is defined by CommitMetadata.roll_candidate.

  There are two ways that rolling a repo can move commits:

    1) As dependencies. Rolling repo A that depends on (B, C) will take
       a penalty for each commit that B and C need to move in order to be
       compatible with the new A revision.

    2) As dependees. Rolling repo A which is depended on by (B, C) will take
       a penalty for each commit that B and C need to move in order to be
       compatible with the new A revision.

  Each repo is analyzed with these two rules and a score is computed. The score
  may be negative if one of the other repos (e.g. B or C) needs A to catch up
  (say that B already rolled forward, and now it requires that its dependency
  A needs to roll forward too).

  As a tiebreaker, the commit with the lowest commit timestamp will be picked.
  So if two repos cause the same amount of global commit movement, the "older"
  of the two commits will roll first. Clearly this is best-effort as there's no
  meaningful enforcement of timestamps between different repos, but it's usually
  close enough to reality to be helpful. This is done to reflect a realistic
  commit ordering; it doesn't make sense for two independent dependencies to
  move such that a very large time gap develops between them (assuming the
  timestamps are sensible). All that said, the precise timestamp value is not
  necessary for the correctness of the algorithm, since it's only involvement is
  a tiebreaker between otherwise valid choices.

  The repo with the lowest score wins and is returned. Note that rolling this
  repo does NOT guarantee a consistent dependency graph. This is OK, as it means
  that the outer loop will just call this function multiple times to roll each
  best repo until there's a consistent graph.

  Args:
    repos (dict(project_id, CommitList)) - The repos to analyze. This function
      will only read from the dict and CommitLists (it will not modify them).

  Returns (str) - The project_id of the repo to advance next.
  """
  # The project_ids of all the repos that can move
  repo_set = set(repos)

  best_project_id = None
  best_score = ()  # (# commits moved, timestamp)

  for project_id, clist in repos.iteritems():
    assert isinstance(clist, CommitList)
    candidate, movement_score = clist.next_roll_candidate
    if not candidate:
      continue

    unaccounted_repos = set(repo_set)

    # first, determine if rolling this repo will force other repos to move.
    for d_pid, dep in candidate.spec.deps.iteritems():
      unaccounted_repos.discard(d_pid)
      movement_score += repos[d_pid].dist_to(dep.revision)

    # Next, see if any unaccounted_repos depend on this repo.
    for pid in unaccounted_repos:
      movement_score += repos[pid].dist_compatible_with(pid, candidate.revision)

    score = (movement_score, candidate.commit_timestamp)
    if not best_score or score < best_score:
      best_score = score
      best_project_id = project_id

  return best_project_id


def is_consistent(spec_pb, repos):
  for pid in spec_pb.deps:
    for d_pid, dep in repos[pid].current.spec.deps.iteritems():
      if dep.revision != spec_pb.deps[d_pid].revision:
        return False
  return True


def _get_roll_candidates_impl(context, package_spec, repos):
  current_pb = package_spec.spec_pb

  ret_good = []
  ret_bad = []

  while True:
    best_project_id = find_best_rev(repos)
    if best_project_id is None:
      # end when there's no best rev to roll
      return ret_good, ret_bad

    rev = repos[best_project_id].advance()
    if not rev:
      return ret_good, ret_bad

    for d_pid, dep in sorted(rev.spec.deps.items()):
      if not repos[d_pid].advance_to(dep.revision):
        return ret_good, ret_bad

    # TODO(iannucci): rationalize what happens if there's a conflict in e.g.
    # branch/url.

    # First, copy all revisions from clists to current_pb. Note that this will
    # accumulate new repos! Because we don't have a quick way to evaluate
    # implicit vs. explicit repo dependencies, we can't algorithmically remove
    # them currently.
    #
    # However, we expect this to be a pretty uncommon case, and removing them by
    # hand should be sufficient for now.
    #
    # If someone really wants to make it automatic, they'll need to make a quick
    # way to scan all DEPS within the current repo to see which packages are
    # actually used. If you have this information, then removing a repo here
    # would be easy (if we don't directly depend on it and none of our
    # immediate dependencies list it, then we can remove it).
    for pid, clist in repos.iteritems():
      current_pb.deps[pid].revision = clist.current.revision

    # Next, copy ONE instance of any new repos
    for pid in current_pb.deps:
      for d_pid, dep in repos[pid].current.spec.deps.iteritems():
        if d_pid not in current_pb.deps:
          current_pb.deps[d_pid].CopyFrom(dep)

    if not is_consistent(current_pb, repos):
      ret_bad.append(RollCandidate(current_pb))
    else:
      ret_good.append(RollCandidate(current_pb))

      # See if this roll introduced any new dependencies we need to worry about
      # going forward.
      new_repos = set(current_pb.deps) - set(repos)
      if new_repos:
        # Going forward we have to account for the new repos. current_pb has all
        # the old and new repos already.
        package_spec = package.PackageSpec.from_package_pb(context, current_pb)
        package_spec.ensure_up_to_date(context)

        # Add any newly discovered repos to our repos set. We don't replace
        # repos because we want to keep the metadata for all already-rolled
        # revisions.
        repos.update(get_commitlists({
          pid: repo_spec
          for pid, repo_spec in package_spec.deps.iteritems()
          if pid in new_repos
        }))


def get_roll_candidates(context, package_spec):
  """Returns a list of RollCandidate objects.

  Args:
    context (PackageContext)
    package_spec (PackageSpec)

  Returns:
    good_candidates (list(RollCandidate)) - The list of valid roll candidates in
      least-changed to most-changed order.
    bad_candidates (list(RollCandidate)) - The list of invalid (but considered)
      roll candidates.
    repos (dict(project_id, CommitList)) - A repos dictionary suitable for
      invoking RollCandidate.changelist().
  """
  start = time.time()

  # not on py3 so we can't use print(..., flush=True) :(
  sys.stdout.write('finding roll candidates... ')
  sys.stdout.flush()

  repos = get_commitlists(package_spec.deps)
  ret_good, ret_bad = _get_roll_candidates_impl(context, package_spec, repos)

  print('found %d/%d good/bad candidates in %0.2f seconds' % (
    len(ret_good), len(ret_bad), time.time()-start))
  sys.stdout.flush()
  return ret_good, ret_bad, repos
