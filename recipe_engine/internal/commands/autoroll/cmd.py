# Copyright 2016 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import logging
import os
import sys
from typing import Any

from gevent import subprocess
from google.protobuf import json_format as jsonpb
from google.protobuf import message

from ... import recipe_deps as recipe_deps_module
from ... import simple_cfg
from ...autoroll_impl import candidate_algorithm
from ...autoroll_impl import commit_list
from ...autoroll_impl import roll_candidate


LOGGER = logging.getLogger(__name__)

IS_WIN = sys.platform.startswith(('win', 'cygwin'))
VPYTHON3 = 'vpython3' + ('.bat' if IS_WIN else '')
GIT = 'git' + ('.bat' if IS_WIN else '')


def _toPBDict(spec: message.Message) -> dict[str, Any]:
  ret = jsonpb.MessageToDict(spec, preserving_proto_field_name=True)
  # HACK: For recipe specs we want to convert py3_only &&
  # require_py3_compatibility to just py3_only (and, hopefully soon, we can
  # remove both of them).
  if ret.get('require_py3_compatibility', False) and ret.get('py3_only', False):
    del ret['require_py3_compatibility']
  return ret


def write_global_files_to_main_repo(
    recipe_deps: recipe_deps_module.RecipeDeps, spec: Any
) -> None:
  """Writes the recipes.cfg and recipes.py scripts to the main repo on disk.

  This pulls `recipes.py` from the current 'recipe_engine' dep in recipe_deps.

  Args:
    * recipe_deps (RecipeDeps) - The loaded recipe dependencies; the destination
      repo is `recipe_deps.main_repo`.
    * spec (proto message RepoSpec) - The RepoSpec proto to write to
      recipes.cfg.
  """
  main_repo = recipe_deps.main_repo
  if spec.project_id:
    spec.repo_name = spec.project_id
  # Format recipes.cfg nicely and make it deterministic.
  out = json.dumps(
      _toPBDict(spec),
      indent=2,
      sort_keys=True,
  ).replace(' \n', '\n') + '\n'
  LOGGER.info('writing: %s', out)

  cfg_path = os.path.join(main_repo.path, simple_cfg.RECIPES_CFG_LOCATION_REL)
  with open(cfg_path, 'w') as cfg_file:
    cfg_file.write(out)

  engine = recipe_deps.repos['recipe_engine']
  assert engine.backend is not None
  recipes_py_path = os.path.join(main_repo.recipes_root_path, 'recipes.py')
  with open(recipes_py_path, 'w') as recipes_py:
    recipes_py.write(engine.backend.cat_file(
        spec.deps['recipe_engine'].revision, 'recipes.py'))


def run_simulation_test(
    repo: recipe_deps_module.RecipeRepo, *additional_args: str
) -> tuple[int, str]:
  """Runs the recipe simulation test for given repo.

  Returns a tuple of exit code and output.
  """
  args = [
      VPYTHON3,
      os.path.join(repo.recipes_root_path, 'recipes.py'),
      'test',
  ] + list(additional_args)
  proc = subprocess.Popen(
      args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
  output, _ = proc.communicate()
  retcode = proc.returncode
  return retcode, output


def regen_docs(repo: recipe_deps_module.RecipeRepo) -> None:
  """Regenerates README.recipes.md.

  Raises a CalledProcessError on failure.
  """
  subprocess.check_call([
    VPYTHON3, os.path.join(repo.recipes_root_path, 'recipes.py'), 'doc',
    '--kind', 'gen',
  ])


def process_candidates(
    recipe_deps: recipe_deps_module.RecipeDeps,
    candidates: list[roll_candidate.RollCandidate],
    repos: Mapping[str, commit_list.CommitList],
    verbose_json: bool,
) -> tuple[bool | None, dict[str, Any] | None, list[dict[str, Any]]]:
  """This processes a list of candidates by running simulation tests to find the
  'best' roll.

  The candidates are listed in the order of 'least commits implied by this roll'
  to 'most commits implied by this roll'.

  This algorithm will try to find:
    1. The biggest roll candidate which does not change the expectations (a
       "trivial" roll).
    2. The smallest roll candidate which changes the expectations but otherwise
       trains successfully (a "non-trivial" roll).

  If it fails to find either of those, it gives up.

  Args:
    * recipe_deps (RecipeDeps)
    * candidates (List[RollCandidate]): A list of valid (self-consistent) roll
      candidates to try in least-changes to most-changes order.
    * repos (Dict[repo_name: str, CommitList]): A repos dictionary suitable for
      invoking RollCandidate.changelist().
    * verbose_json (bool): Causes the returned `roll_details` to include
      additional information. See roll_details below.

  TODO(iannucci, probably): Stop passing around all these Dicts and use some
  real objects.

  Returns a 3-tuple:
    * trivial (bool): If the picked roll was trivial or not.
    * picked_roll_details (Dict[...]): A copy of one of the dictionaries in
      `roll_details`. This is the roll which was selected.
    * roll_details (List[Dict[...]]): A list of dictionaries like:
      * spec (JSONPB encoding of the picked RepoSpec)
      * commit_infos (Dict[repo_name: str, List[Dict[...]]]): The mapping of
        repo to commit information for all repos which advanced for this roll.
        It contains:
        * author_email (str): The author of this commit.
        * message_lines (List[str]): The commit message. If verbose_json is
          False this only contains the first line.
        * revision (str): The git commit id for this commit.
      * recipes_simulation_test (Dict[...]): If verbose_json is true, this will
        be set if we ran `test run` on this roll. Contains:
        * output (str): The full combined stdout/stderr from the test command.
        * retcode (int): The return code of the test command.
      * recipes_simulation_test_train (Dict[...]): If verbose_json is true,
        this will be set if we ran `test train` on this roll. Contains:
        * output (str): The full combined stdout/stderr from the test command.
        * retcode (int): The return code of the test command.
  """
  roll_details: list[dict[str, Any]] = []
  trivial = None
  picked_roll_details = None

  # Rest of the function assumes this is big-to-small candidates.
  candidates.reverse()

  print('looking for a trivial roll...')

  # Fill basic information about all the candidates. In later loops
  # we exit early depending on test results.
  for candidate in candidates:
    roll_details.append({
        'spec': _toPBDict(candidate.repo_spec),
        'commit_infos': {
            repo_name: [{
                'author_email': c.author_email,
                'message_lines':
                    (c.message_lines if verbose_json else c.message_lines[:1]),
                'revision': c.revision,
            } for c in clist]
            for repo_name, clist in candidate.changelist(repos).items()
        },
    })

  # Process candidates biggest first. If the roll is trivial, we want
  # the maximal one, e.g. to jump over some reverts, or include fixes
  # landed later for incompatible API changes.
  for i, candidate in enumerate(candidates):
    print('* processing candidate #%d... ' % (i + 1))

    write_global_files_to_main_repo(recipe_deps, candidate.repo_spec)

    retcode, output = run_simulation_test(
        recipe_deps.main_repo, 'run', '--no-docs')

    if verbose_json:
      roll_details[i]['recipes_simulation_test'] = {
        'output': output,
        'rc': retcode,
      }

    LOGGER.info('output:\n%s', output)
    if retcode == 0:
      print('  SUCCESS!')
      trivial = True
      picked_roll_details = roll_details[i]
      break
    else:
      print('  FAILED')

  if not picked_roll_details:
    print('looking for a nontrivial roll...')

    # Process candidates smallest first. If the roll is going to change
    # expectations, it should be minimal to avoid pulling too many unrelated
    # changes.
    for i, candidate in reversed(list(enumerate(candidates))):
      print('* processing candidate #%d... ' % (i + 1))

      write_global_files_to_main_repo(recipe_deps, candidate.repo_spec)

      retcode, output = run_simulation_test(
          recipe_deps.main_repo, 'train', '--no-docs')
      if verbose_json:
        roll_details[i]['recipes_simulation_test_train'] = {
          'output': output,
          'rc': retcode,
        }

      LOGGER.info('output:\n%s', output)
      if retcode == 0:
        print('  SUCCESS!')
        trivial = False
        picked_roll_details = roll_details[i]
        break
      else:
        print('  FAILED')

  return trivial, picked_roll_details, roll_details


def test_rolls(
    recipe_deps: recipe_deps_module.RecipeDeps, verbose_json: bool
) -> dict[str, Any]:
  candidates, rejected_candidates, repos = (
      candidate_algorithm.get_roll_candidates(recipe_deps)
  )

  roll_details: list[dict[str, Any]] = []
  picked_roll_details = None
  trivial: bool | None = True
  if candidates:
    trivial, picked_roll_details, roll_details = process_candidates(
        recipe_deps, candidates, repos, verbose_json)

  ret: dict[str, Any] = {
    # it counts as success if there are no candidates at all :)
    'success': bool(not candidates or picked_roll_details),
    'trivial': trivial,
    'roll_details': roll_details,
    'picked_roll_details': picked_roll_details,
    'rejected_candidates_count': len(rejected_candidates),
  }
  if verbose_json:
    ret['rejected_candidate_specs'] = [
        _toPBDict(c.repo_spec) for c in rejected_candidates
    ]
  return ret


def main(args: argparse.Namespace) -> int:
  original_spec = args.recipe_deps.main_repo.recipes_cfg_pb2

  # Fetch all remote changes locally, so we can compute metadata for them.
  for repo in args.recipe_deps.repos.values():
    if repo.name == args.recipe_deps.main_repo_id:
      continue
    repo.backend.fetch(original_spec.deps[repo.name].branch)

  results: dict[str, Any] = {}
  try:
    results = test_rolls(args.recipe_deps, args.verbose_json)
  finally:
    if not results.get('success'):
      # Restore initial state. Since we could be running simulation tests
      # on other revisions, re-run them now as well.
      write_global_files_to_main_repo(args.recipe_deps, original_spec)
      run_simulation_test(args.recipe_deps.main_repo, 'train')
    elif results.get('picked_roll_details'):
      # Success!
      if not args.recipe_deps.main_repo.recipes_cfg_pb2.no_docs:
        regen_docs(args.recipe_deps.main_repo)

  if args.output_json:
    with args.output_json:
      json.dump(results, args.output_json, sort_keys=True, indent=2)

  return 0
