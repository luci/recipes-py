# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import logging
import os
import sys
import time

from ...fetch import GitBackend

from .commit_list import CommitList
from .roll_candidate import RollCandidate

LOGGER = logging.getLogger(__name__)


def find_best_rev(repos):
  """Returns the repo_name of the best repo to roll.

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
    repos (dict(repo_name, CommitList)) - The repos to analyze. This function
      will only read from the dict and CommitLists (it will not modify them).

  Returns (str) - The repo_name of the repo to advance next.
  """
  # The repo_name of all the repos that can move
  repo_set = set(repos)

  best_repo_name = None
  best_score = ()  # (# commits moved, timestamp)

  for repo_name, clist in repos.iteritems():
    assert isinstance(clist, CommitList)
    candidate, movement_score = clist.next_roll_candidate
    if not candidate:
      continue

    unaccounted_repos = set(repo_set)

    # first, determine if rolling this repo will force other repos to move.
    for d_pid, dep in candidate.spec.deps.iteritems():
      unaccounted_repos.discard(d_pid)
      if d_pid in repos:
        movement_score += repos[d_pid].dist_to(dep.revision)
      else:
        # d_pid is a NEW repo that this roll pulls in. Arbitrarially give this
        # a high movement score so that we're more likely to roll all other
        # repos first.
        movement_score += 100

    # Next, see if any unaccounted_repos depend on this repo.
    for pid in unaccounted_repos:
      movement_score += repos[pid].dist_compatible_with(pid, candidate.revision)

    score = (movement_score, candidate.commit_timestamp)
    if not best_score or score < best_score:
      best_score = score
      best_repo_name = repo_name

  return best_repo_name


def is_consistent(spec_pb, repos):
  """
  Args:
    * spec_pb (RepoSpec) - The spec to check for consistency
    * repos (Dict[repo_name: str, CommitList]) - The commit list mapping of all
      known repos.
  """
  for repo_name, toplevel_dep in spec_pb.deps.iteritems():
    if repo_name not in repos:
      continue
    for dep_name, dep in repos[repo_name].current.spec.deps.iteritems():
      if dep.revision != spec_pb.deps[dep_name].revision:
        LOGGER.info(
            ('manifest has %s@%s, but this depends on %s@%s, but this '
             'conflicts with manifests version of %s'),
            repo_name, toplevel_dep.revision,
            dep_name, dep.revision,
            spec_pb.deps[dep_name].revision)
        return False
  return True


def _get_roll_candidates_impl(recipe_deps, repos):
  if LOGGER.isEnabledFor(logging.DEBUG):
    count = sum(len(r) for r in repos.itervalues())
    LOGGER.debug('analyzing %d commits across %d repos', count, len(repos))

  current_pb = recipe_deps.main_repo.recipes_cfg_pb2

  ret_good = []
  ret_bad = []

  while True:
    best_repo_name = find_best_rev(repos)
    if best_repo_name is None:
      # end when there's no best rev to roll
      LOGGER.debug("terminating: no best project")
      return ret_good, ret_bad

    rev = repos[best_repo_name].advance()
    if not rev:
      LOGGER.debug("terminating: could not advance %r", best_repo_name)
      return ret_good, ret_bad

    backwards_roll = False
    for d_pid, dep in sorted(rev.spec.deps.items()):
      if d_pid in repos and not repos[d_pid].advance_to(dep.revision):
        backwards_roll = True
        LOGGER.debug("backwards_roll: rolling %r to %r causes (%r->%r)",
                     best_repo_name, rev.revision, d_pid, dep.revision)
        break

    # TODO(iannucci): rationalize what happens if there's a conflict in e.g.
    # branch/url.

    # First, copy all revisions from clists to current_pb. Note that this will
    # accumulate all new repos during this entire roll process! Because we don't
    # have a quick way to evaluate implicit vs. explicit repo dependencies, we
    # can't algorithmically remove them currently.
    #
    # However, we expect this to be a pretty uncommon case, and removing them by
    # hand should be sufficient for now.
    #
    # If someone really wants to make it automatic, they'll need to make a quick
    # way to scan all DEPS within the current repo to see which repos are
    # actually used. If you have this information, then removing a repo here
    # would be easy (if we don't directly depend on it and none of our
    # immediate dependencies list it, then we can remove it).
    for pid, clist in repos.iteritems():
      current_pb.deps[pid].revision = clist.current.revision

    # See if this roll introduced any new dependencies we need to worry about
    # going forward. Going forward we have to account for the new repos.
    # current_pb has all the old and new repos already.
    new_repos = set(current_pb.deps) - set(repos)
    if new_repos:
      for repo_name in new_repos:
        dep = current_pb.deps[repo_name]

        # We check it out in the `.recipe_deps` folder. This is a slight
        # abstraction leak, but adding this to RecipeDeps just for autoroller
        # seemed like a worse alternative.
        dep_path = os.path.join(recipe_deps.recipe_deps_path, repo_name)
        backend = GitBackend(dep_path, dep.url)
        backend.checkout(dep.revision)

        # Add any newly discovered repos to our repos set. We don't replace
        # repos because we want to keep the metadata for all already-rolled
        # revisions.
        repos[repo_name] = CommitList.from_backend(dep, backend)

    # Next, copy ONE instance of any new repos
    for pid in current_pb.deps.keys():
      for d_pid, dep in repos[pid].current.spec.deps.iteritems():
        if d_pid not in current_pb.deps:
          current_pb.deps[d_pid].url = dep.url
          current_pb.deps[d_pid].revision = dep.revision
          current_pb.deps[d_pid].branch = dep.branch

    if backwards_roll or not is_consistent(current_pb, repos):
      LOGGER.debug("skipping: not_consistent")
      ret_bad.append(RollCandidate(current_pb))
    else:
      ret_good.append(RollCandidate(current_pb))


def get_roll_candidates(recipe_deps):
  """Returns a list of RollCandidate objects.

  Prints diagnostic information to stderr.

  Args:
    * recipe_deps (RecipeDeps)

  Returns:
    good_candidates (list(RollCandidate)) - The list of valid roll candidates in
      least-changed to most-changed order.
    bad_candidates (list(RollCandidate)) - The list of invalid (but considered)
      roll candidates.
    repos (dict(repo_name, CommitList)) - A repos dictionary suitable for
      invoking RollCandidate.changelist().
  """
  if not all(repo.backend for repo in recipe_deps.repos.itervalues()):
    raise ValueError('get_roll_candidates does not work with -O overrides.')

  start = time.time()

  print('finding roll candidates... ', file=sys.stderr)
  repos = {
    repo_name: CommitList.from_backend(
        recipe_deps.main_repo.simple_cfg.deps[repo_name],
        repo.backend)
    for repo_name, repo in recipe_deps.repos.iteritems()
    if repo_name != recipe_deps.main_repo_id
  }

  for repo, commits in repos.iteritems():
    print('  %s: %d commits' % (repo, len(commits)), file=sys.stderr)
  sys.stdout.flush()

  ret_good, ret_bad = _get_roll_candidates_impl(recipe_deps, repos)

  print('found %d/%d good/bad candidates in %0.2f seconds' % (
    len(ret_good), len(ret_bad), time.time()-start), file=sys.stderr)
  sys.stdout.flush()
  return ret_good, ret_bad, repos
