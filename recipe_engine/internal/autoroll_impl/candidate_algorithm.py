# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import collections
import functools
import logging
import os
import sys
import time

from future.utils import iteritems, itervalues

from ..fetch import GitBackend

from .commit_list import CommitList
from .roll_candidate import RollCandidate

LOGGER = logging.getLogger(__name__)


class _Config(collections.Mapping):
  """An immutable mapping type storing the revisions to pin repos to.

  Instances are hashable and in contrast to FrozenDict, the equality
  comparison ignores iteration order.

  Instances do not necessarily represent a complete config.
  """

  def __init__(self, revisions_by_repo):
    self._revisions_by_repo = dict(revisions_by_repo)
    # Calculate the hash immediately so that we know all the items are
    # hashable too.
    self._hash = hash(tuple(sorted(iteritems(self._revisions_by_repo))))

  def __hash__(self):
    return self._hash

  def __getitem__(self, key):
    return self._revisions_by_repo[key]

  def __iter__(self):
    return iter(self._revisions_by_repo)

  def __len__(self):
    return len(self._revisions_by_repo)

  def __str__(self):
    return '{}({})'.format(type(self).__name__, self._revisions_by_repo)


def memoize(f):
  """Decorator that can be applied to a method to memoize the results.

  Args:
    f - The function to decorate with memoization. The first argument of
      the function should be self - the instance of the class. The
      function can take an arbitrary amount of additional positional
      arguments. All arguments must be hashable.

  Returns:
    A function wrapping `f`. `f` will be executed only once for a given
    set of input arguments.
  """

  cache = {}

  @functools.wraps(f)
  def cached(self, *args):
    if args in cache:
      return cache[args]
    ret = f(self, *args)
    cache[args] = ret
    return ret

  return cached


class _ConfigFinder(object):

  def __init__(self, commit_lists_by_repo, new_repo_commit_list_getter):
    self._commit_lists_by_repo = commit_lists_by_repo
    self._new_repo_commit_list_getter = new_repo_commit_list_getter

  @memoize
  def find_configs(self, repo, revision, repos_to_pin):
    """Find configs for candidate commits.

    Args:
      repo (str) - The repo to perform the starting pin on.
      revision (str) - The commit hash value to use for the starting pin.
      repos_to_pin (set(str)) - The repos that need to be pinned by the
        resulting configs. Additional repos may be pinned if a commit
        adds new dependencies.

    Returns:
      A set of configs where each config is a mapping from the repo name
      to the revision to be used for the repo. The config will contain
      entries for all of the provided top level repos and all of their
      dependencies, which may contain new repos. The configs are
      guaranteed to be consistent but may roll some repos backwards.
    """
    commit = self._commit_lists_by_repo[repo].lookup(revision)
    config = {}
    repos_to_pin = set(repos_to_pin)
    configs = set()
    if self._pin(config, repo, commit, repos_to_pin):
      configs.update(
          self._find_configs_impl(_Config(config), frozenset(repos_to_pin)))
    else:
      LOGGER.info('No consistent configs could be created by pinning %s to %s',
                  repo, revision)
    return configs

  # This is cached so that if there are multiple top level repos, when a config
  # is chosen that only moves one of them, the configs that were computed for
  # moving the other pin don't need to be recomputed (assuming no repo becomes a
  # top level repo due to a dependency edge being removed). This requires that
  # the arguments are hashable (_Config and frozenset). This also requires that
  # the implementation not use cursors into the commit lists as that would
  # invalidate results when the cursors are advanced.
  @memoize
  def _find_configs_impl(self, config, repos_to_pin):
    if not repos_to_pin:
      return [config]

    repo = next(iter(repos_to_pin))

    configs = set()
    for commit in self._commit_lists_by_repo[repo].compatible_commits(config):
      pinned = dict(config)
      to_pin = set(repos_to_pin)
      if self._pin(pinned, repo, commit, to_pin):
        configs.update(
            self._find_configs_impl(_Config(pinned), frozenset(to_pin)))

    return configs

  def _pin(self, config, repo, commit, repos_to_pin):
    config[repo] = commit.revision
    new_pins_by_repo = {}
    for dep_repo, dep in iteritems(commit.spec.deps):
      if dep_repo not in repos_to_pin and dep_repo not in config:
        new_pins_by_repo[dep_repo] = dep
      config[dep_repo] = dep.revision
    repos_to_pin.difference_update(config)

    for dep_repo, dep in iteritems(new_pins_by_repo):
      clist = self._new_repo_commit_list_getter(dep_repo, dep)
      if not clist.is_compatible(dep.revision, config):
        return False
      dep_commit = clist.lookup(dep.revision)
      if not self._pin(config, dep_repo, dep_commit, repos_to_pin):
        return False

    return True


def _score(commit_lists_by_repo, config, current_config, top_level_repos):
  backwards_rolls = 0
  new_deps = 0
  movement = 0
  timestamp = 0

  for repo, revision in iteritems(config):
    clist = commit_lists_by_repo[repo]
    if repo not in current_config:
      new_deps += 1
      movement += clist.dist(revision)
    else:
      dist = clist.dist(current_config[repo], revision)
      # If it's moving backwards, it doesn't matter how far, just increment the
      # count of backwards rolls, which are compared before the movement
      if dist is None:
        backwards_rolls += 1
      else:
        movement += dist

  timestamp = max(commit_lists_by_repo[repo].lookup(revision).commit_timestamp
                  for repo, revision in iteritems(config)
                  if repo in top_level_repos)

  return backwards_rolls, new_deps, movement, timestamp


class _CandidateCallback:

  def __init__(self):
    self._accepted = False

  @property
  def accepted(self):
    return self._accepted

  def accept(self):
    self._accepted = True


def _get_roll_candidates_impl(recipe_deps, commit_lists_by_repo):
  """Generator for configs to try rolling.

  All yielded configs will be consistent; configs are produced by
  creating partial configs based on varying a single top-level pin and
  successively updating the config with the commits for each other
  top-level pin that are consistent with the partial config.

  If the incoming config is consistent, all yielded configs will involve
  at least one "interesting" commit being rolled, where "interesting"
  means "the commit modifies one or more recipe related files", and is
  defined by CommitMetadata.roll_candidate. If the incoming config is
  not consistent, then some configs may be initially yielded that do not
  roll any "interesting" commits.

  Configs are yielded in increasing order of the commit movement across
  all repos, with new deps and backwards rolls being considered larger
  movement than advancing an existing pin any amount.

  As a tiebreaker, the commit with the lowest commit timestamp will be
  picked. So if two repos cause the same amount of global commit
  movement, the "older" of the two commits will roll first. Clearly this
  is best-effort as there's no meaningful enforcement of timestamps
  between different repos, but it's usually close enough to reality to
  be helpful. This is done to reflect a realistic commit ordering; it
  doesn't make sense for two independent dependencies to move such that
  a very large time gap develops between them (assuming the timestamps
  are sensible). All that said, the precise timestamp value is not
  necessary for the correctness of the algorithm, since it's only
  involvement is a tiebreaker between otherwise valid choices.

  Args:
    recipe_deps (RecipeDeps) - The recipe deps object.
    commit_lists_by_repo (dict(str, CommitList)) - Mapping from repo
      name to the commits for the repo. This will be updated as new
      repos are added.

  Returns:
    A generator that yields pairs of config objects. The config objects
    are mappings from repo name to the revision for the repo. The
    configs will include all repos that should be set in recipes.cfg,
    not just those that have changed. The first element is the currently
    accepted config and the second is the candidate config. The caller
    should send a boolean value to the generator indicating whether the
    config was accpted or not, which will affect how subsequent configs
    are generated. Any value sent before the first yield will be
    ignored.
  """

  # Cache of backends for new repos, the backend caches resolved refspecs, so
  # this will prevent repeated network traffic for the same repo
  new_backends_by_repo = {}

  # Local function so that it can use the value of current_config
  def get_new_repo_commit_list(repo, dep):
    # Once a repo is incorporated into the current config, we will no
    # longer re-fetch it
    assert repo not in current_config, '{} is in current config: {}'.format(
        repo, current_config)
    if repo in commit_lists_by_repo:
      clist = commit_lists_by_repo[repo]
      try:
        clist.lookup(dep.revision)
      except:
        pass
      else:
        return clist

    backend = new_backends_by_repo.get(repo)
    if backend is None:
      # We check it out in the `.recipe_deps` folder. This is a slight
      # abstraction leak, but adding this to RecipeDeps just for autoroller
      # seemed like a worse alternative.
      dep_path = os.path.join(recipe_deps.recipe_deps_path, repo)
      backend = GitBackend(dep_path, dep.url)
      backend.checkout(dep.branch, dep.revision)

    clist = CommitList.from_backend(dep, backend)
    commit_lists_by_repo[repo] = clist
    return clist

  config_finder = _ConfigFinder(commit_lists_by_repo, get_new_repo_commit_list)

  # Tracks the commits we make candidates from
  cursors_by_repo = {
      repo: clist.cursor() for repo, clist in iteritems(commit_lists_by_repo)
  }

  # Tracks the currently accepted config for the purposes of comparison/scoring,
  # determining which repos are top level (and therefore do not have their
  # revisions explicitly set by other repos) and determining which repos must be
  # pinned by new configs
  current_config = _Config({
      repo: cursor.current.revision
      for repo, cursor in iteritems(cursors_by_repo)
  })
  top_level_repos = None
  yielded_configs = set([current_config])

  while True:
    if top_level_repos is None:
      top_level_repos = set(current_config)
      for repo, revision in iteritems(current_config):
        commit = commit_lists_by_repo[repo].lookup(revision)
        top_level_repos.difference_update(commit.spec.deps)
      top_level_repos = frozenset(top_level_repos)

    candidate_configs = set()
    for repo, cursor in iteritems(cursors_by_repo):
      if repo not in top_level_repos:
        continue
      commit = cursor.current
      candidate_configs.update(
          config_finder.find_configs(repo, commit.revision, current_config))
    candidate_configs.difference_update(yielded_configs)

    # Because all yielded configs have been removed, at this point, one of the
    # following conditions is true for each of the candidate configs:
    # 1. The config has never been produced by the config finder before; the
    #    score must be computed for the first time
    # 2. The config has been produced by the config finder in a previous round
    #    but a lower-scoring config in the round was accepted; the score must be
    #    re-computed because the current config has changed
    # So there's no opportunity for caching the scores.
    key_fn = (lambda c: _score(commit_lists_by_repo, c, current_config,
                               top_level_repos))
    candidate_configs = sorted(candidate_configs, key=key_fn)

    for candidate_config in candidate_configs:
      yielded_configs.add(candidate_config)
      accepted = yield current_config, candidate_config
      if accepted:
        new_revisions = candidate_config
        current_config = candidate_config
        # Setting top_level_repos to None will cause it to be recomputed at the
        # start of the next round in case a change removed a dependency edge
        # creating a new top level repo
        top_level_repos = None
        break
    else:
      new_revisions = {}
      # Only advance the top level repos, the revisions of the top level repos
      # determine the revisions of other repos. The cursors for the other repos
      # will be updated when configs are accepted.
      for repo in top_level_repos:
        next_candidate = cursors_by_repo[repo].next_roll_candidate
        if next_candidate:
          new_revisions[repo] = next_candidate.revision

      # There are no more candidates
      if not new_revisions:
        return

    for repo, revision in iteritems(new_revisions):
      cursor = cursors_by_repo.get(repo)
      if cursor is None:
        cursor = commit_lists_by_repo[repo].cursor()
        cursors_by_repo[repo] = cursor
      cursor.advance_to(revision)


def _report_commit_counts(commit_lists_by_repo):
  commits_to_consider = {
      r: len(commits) - 1
      for r, commits in iteritems(commit_lists_by_repo)
      if len(commits) > 1
  }
  for repo, commits in iteritems(commits_to_consider):
    print('  %s: %d commits' % (repo, commits), file=sys.stderr)
  if LOGGER.isEnabledFor(logging.INFO):
    count = sum(commits_to_consider.values())
    LOGGER.info('analyzing %d commits across %d repos', count,
                len(commits_to_consider))
  sys.stdout.flush()


def _describe_candidate_config(current_config, candidate_config,
                               commit_lists_by_repo):
  config_description = []
  for repo, revision in iteritems(candidate_config):
    if repo not in current_config:
      prev_revision = '*not set*'
      dist_description = 'new'
    else:
      prev_revision = current_config[repo]
      dist = commit_lists_by_repo[repo].dist(prev_revision, revision)
      if dist == 0:
        continue
      if dist is None:
        dist_description = 'backwards'
      else:
        dist_description = '{} commits'.format(dist)
    config_description.append('    {}: {} -> {} ({})'.format(
        repo, prev_revision, revision, dist_description))
  return '\n'.join(config_description)


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
  if not all(repo.backend for repo in itervalues(recipe_deps.repos)):
    raise ValueError('get_roll_candidates does not work with -O overrides.')

  start = time.time()

  print('finding roll candidates... ', file=sys.stderr)
  commit_lists_by_repo = {
      repo_name:
      CommitList.from_backend(recipe_deps.main_repo.simple_cfg.deps[repo_name],
                              repo.backend)
      for repo_name, repo in iteritems(recipe_deps.repos)
      if repo_name != recipe_deps.main_repo_id
  }

  _report_commit_counts(commit_lists_by_repo)

  current_pb = recipe_deps.main_repo.recipes_cfg_pb2

  good_candidates = []
  bad_candidates = []

  candidates_generator = _get_roll_candidates_impl(recipe_deps,
                                                   commit_lists_by_repo)

  # The initial value of accepted does not matter, the generator only
  # uses the sent value after yielding
  accepted = None
  i = 0
  while True:
    try:
      current_config, candidate_config = candidates_generator.send(accepted)
    except StopIteration:
      break
    i += 1
    accepted = False

    if LOGGER.isEnabledFor(logging.INFO):
      config_description = _describe_candidate_config(current_config,
                                                      candidate_config,
                                                      commit_lists_by_repo)
      LOGGER.info("Checking config #%s\n%s", i, config_description)

    # TODO(iannucci): rationalize what happens if there's a conflict in e.g.
    # branch/url.
    for repo, revision in iteritems(candidate_config):
      if repo not in current_pb.deps:
        clist = commit_lists_by_repo[repo]
        current_pb.deps[repo].url = clist.url
        current_pb.deps[repo].branch = clist.branch
      current_pb.deps[repo].revision = revision

    backwards_roll = False
    for repo, revision in iteritems(current_config):
      clist = commit_lists_by_repo[repo]
      if clist.dist(revision, candidate_config[repo]) is None:
        backwards_roll = True
        break
    if backwards_roll:
      LOGGER.info('rejecting config #%s due to backwards roll', i)
      bad_candidates.append(RollCandidate(current_pb))
    else:
      LOGGER.info('config #%s accepted', i)
      good_candidates.append(RollCandidate(current_pb))
      # Signal that the config is accepted so that the _impl function will start
      # a new round using this config as the current config
      accepted = True

  LOGGER.info("terminating: no more candidates")

  print(
      'found %d/%d good/bad candidates in %0.2f seconds' %
      (len(good_candidates), len(bad_candidates), time.time() - start),
      file=sys.stderr)
  sys.stdout.flush()
  return good_candidates, bad_candidates, commit_lists_by_repo
