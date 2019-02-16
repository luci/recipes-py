# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys

from .internal import simple_cfg
from .internal.autoroll_impl.candidate_algorithm import get_roll_candidates

from google.protobuf import json_format as jsonpb


LOGGER = logging.getLogger(__name__)

ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

IS_WIN = sys.platform.startswith(('win', 'cygwin'))
VPYTHON = 'vpython' + ('.bat' if IS_WIN else '')
GIT = 'git' + ('.bat' if IS_WIN else '')

def write_global_files_to_main_repo(recipe_deps, spec):
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
  out = jsonpb.MessageToJson(spec, preserving_proto_field_name=True)
  LOGGER.info('writing: %s', out)

  cfg_path = os.path.join(main_repo.path, simple_cfg.RECIPES_CFG_LOCATION_REL)
  with open(cfg_path, 'wb') as f:
    f.write(out)

  engine = recipe_deps.repos['recipe_engine']
  recipes_py_path = os.path.join(main_repo.recipes_root_path, 'recipes.py')
  with open(recipes_py_path, 'wb') as f:
    f.write(
      engine.backend.cat_file(
        spec.deps['recipe_engine'].revision, 'recipes.py'))


def run_simulation_test(repo, *additional_args):
  """Runs the recipe simulation test for given repo.

  Returns a tuple of exit code and output.
  """
  p = subprocess.Popen([
    VPYTHON, os.path.join(repo.recipes_root_path, 'recipes.py'), 'test',
  ] + list(additional_args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = p.communicate()
  rc = p.returncode
  return rc, output


def regen_docs(repo):
  """Regenerates README.recipes.md.

  Raises a CalledProcessError on failure.
  """
  subprocess.check_call([
    VPYTHON, os.path.join(repo.recipes_root_path, 'recipes.py'), 'doc',
    '--kind', 'gen',
  ])


def process_candidates(recipe_deps, candidates, repos, verbose_json):
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
  roll_details = []
  trivial = None
  picked_roll_details = None

  # Rest of the function assumes this is big-to-small candidates.
  candidates.reverse()

  print('looking for a trivial roll...')

  # Fill basic information about all the candidates. In later loops
  # we exit early depending on test results.
  for candidate in candidates:
    roll_details.append({
      'spec': jsonpb.MessageToDict(
          candidate.repo_spec, preserving_proto_field_name=True),
      'commit_infos': {
        repo_name: [{
          'author_email': c.author_email,
          'message_lines': (
            c.message_lines if verbose_json else c.message_lines[:1]
          ),
          'revision': c.revision,
        } for c in clist]
        for repo_name, clist in candidate.changelist(repos).iteritems()},
    })

  # Process candidates biggest first. If the roll is trivial, we want
  # the maximal one, e.g. to jump over some reverts, or include fixes
  # landed later for incompatible API changes.
  for i, candidate in enumerate(candidates):
    print('  processing candidate #%d... ' % (i + 1), end='')

    write_global_files_to_main_repo(recipe_deps, candidate.repo_spec)

    retcode, output = run_simulation_test(recipe_deps.main_repo, 'run')
    if verbose_json:
      roll_details[i]['recipes_simulation_test'] = {
        'output': output,
        'rc': retcode,
      }

    if retcode == 0:
      print('SUCCESS!')
      trivial = True
      picked_roll_details = roll_details[i]
      break
    else:
      print('FAILED')

  if not picked_roll_details:
    print('looking for a nontrivial roll...')

    # Process candidates smallest first. If the roll is going to change
    # expectations, it should be minimal to avoid pulling too many unrelated
    # changes.
    for i, candidate in reversed(list(enumerate(candidates))):
      print('  processing candidate #%d... ' % (i + 1), end='')

      write_global_files_to_main_repo(recipe_deps, candidate.repo_spec)

      retcode, output = run_simulation_test(
        recipe_deps.main_repo, 'train', '--no-docs')
      if verbose_json:
        roll_details[i]['recipes_simulation_test_train'] = {
          'output': output,
          'rc': retcode,
        }

      if retcode == 0:
        print('SUCCESS!')
        trivial = False
        picked_roll_details = roll_details[i]
        break
      else:
        print('FAILED')

  return trivial, picked_roll_details, roll_details


def test_rolls(recipe_deps, verbose_json):
  candidates, rejected_candidates, repos = get_roll_candidates(recipe_deps)

  roll_details = []
  picked_roll_details = None
  trivial = True
  if candidates:
    trivial, picked_roll_details, roll_details = process_candidates(
      recipe_deps, candidates, repos, verbose_json)

  ret = {
    # it counts as success if there are no candidates at all :)
    'success': bool(not candidates or picked_roll_details),
    'trivial': trivial,
    'roll_details': roll_details,
    'picked_roll_details': picked_roll_details,
    'rejected_candidates_count': len(rejected_candidates),
  }
  if verbose_json:
    ret['rejected_candidate_specs'] = [
      jsonpb.MessageToDict(c.repo_spec, preserving_proto_field_name=True)
      for c in rejected_candidates
    ]
  return ret


def add_subparser(parser):
  helpstr = 'Roll dependencies of a recipe repo forward.'
  autoroll_p = parser.add_parser(
    'autoroll', help=helpstr, description=helpstr)
  autoroll_p.add_argument(
    '--output-json',
    type=argparse.FileType('w'),
    help='A json file to output information about the roll to.')
  autoroll_p.add_argument(
    '--verbose-json',
    action='store_true',
    help=('Emit even more data in the output-json file. '
          'Requires --output-json.'))

  def postprocess_func(parser, args):
    if args.verbose_json and not args.output_json:
      parser.error('--verbose-json passed without --output-json')

  autoroll_p.set_defaults(
    func=main, postprocess_func=postprocess_func)


def main(args):
  original_spec = args.recipe_deps.main_repo.recipes_cfg_pb2

  # Fetch all remote changes locally, so we can compute metadata for them.
  for repo in args.recipe_deps.repos.itervalues():
    if repo.name == args.recipe_deps.main_repo_id:
      continue
    repo.backend.fetch(original_spec.deps[repo.name].branch)

  results = {}
  try:
    results = test_rolls(args.recipe_deps, args.verbose_json)
  finally:
    if not results.get('success'):
      # Restore initial state. Since we could be running simulation tests
      # on other revisions, re-run them now as well.
      write_global_files_to_main_repo(args.recipe_deps, original_spec)
      run_simulation_test(args.recipe_deps.main_repo, 'train')
    elif results.get('picked_roll_details'):
      # Success! We need to regen docs now.
      regen_docs(args.recipe_deps.main_repo)

  if args.output_json:
    with args.output_json:
      json.dump(results, args.output_json, sort_keys=True, indent=2)

  return 0
