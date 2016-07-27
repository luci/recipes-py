# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import json
import os
import subprocess
import sys

from . import package


ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def default_json_encode(o):
  """Fallback for objects that JSON library can't serialize."""
  if isinstance(o, package.CommitInfo):
    return o.dump()

  return repr(o)


def run_simulation_test(repo_root, package_spec, additional_args=None):
  """
  Runs recipe simulation test for given package.

  Returns a tuple of exit code and output.
  """
  # Use _local_ recipes.py, so that it checks out the pinned recipe engine,
  # rather than running recipe engine which may be at a different revision
  # than the pinned one.
  args = [
    sys.executable,
    os.path.join(repo_root, package_spec.recipes_path, 'recipes.py'),
    'simulation_test',
  ]
  if additional_args:
    args.extend(additional_args)
  p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = p.communicate()
  rc = p.returncode
  return rc, output


def process_candidates(candidates, context, config_file, package_spec):
  roll_details = []
  trivial = None
  picked_roll_details = None

  print('looking for a trivial roll...')

  # Fill basic information about all the candidates. In later loops
  # we exit early depending on test results.
  for candidate in candidates:
    roll_details.append({
      'spec': str(candidate.get_rolled_spec().dump()),
      'diff': candidate.get_diff(),
      'commit_infos': candidate.get_commit_infos(),
    })

  # Process candidates biggest first. If the roll is trivial, we want
  # the maximal one, e.g. to jump over some reverts, or include fixes
  # landed later for incompatible API changes.
  for i, candidate in enumerate(candidates):
    print('  processing candidate #%d... ' % (i + 1), end='')

    config_file.write(candidate.get_rolled_spec().dump())
    rc, output = run_simulation_test(context.repo_root, package_spec)
    roll_details[i]['recipes_simulation_test'] = {
      'output': output,
      'rc': rc,
    }

    if rc == 0:
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

      config_file.write(candidate.get_rolled_spec().dump())

      rc, output = run_simulation_test(
          context.repo_root, package_spec, ['train'])
      roll_details[i]['recipes_simulation_test_train'] = {
        'output': output,
        'rc': rc,
      }

      if rc == 0:
        print('SUCCESS!')
        trivial = False
        picked_roll_details = roll_details[i]
        break
      else:
        print('FAILED')

  return trivial, picked_roll_details, roll_details

def process_rejected(rejected_candidates, projects=None):
  """
  Gets details of (optionally filtered) rejected rolls.

  If the rejected rolls pertain to projects which we don't care about, then we
  ignore them.

  TODO(martiniss): guess which projects to use, using luci-config.
  """
  projects = set(projects or [])
  rejected_candidates_details = []

  for candidate in rejected_candidates:
    if not projects or set(
        candidate.get_affected_projects()).intersection(projects):
      rejected_candidates_details.append(candidate.to_dict())

  return rejected_candidates_details

def test_rolls(config_file, context, package_spec, projects=None):
  print('finding roll candidates...')

  root_spec = package.RootRepoSpec(config_file)
  candidates, rejected_candidates = package_spec.roll_candidates(
      root_spec, context)

  trivial, picked_roll_details, roll_details = process_candidates(
      candidates, context, config_file, package_spec)

  rejected_candidates_details = process_rejected(rejected_candidates, projects)

  return {
    'success': bool(picked_roll_details),
    'trivial': trivial,
    'roll_details': roll_details,
    'picked_roll_details': picked_roll_details,
    'rejected_candidates_details': rejected_candidates_details,
  }


def main(args, repo_root, config_file):
  context = package.PackageContext.from_proto_file(
      repo_root, config_file, allow_fetch=not args.no_fetch)
  package_spec = package.PackageSpec.load_proto(config_file)

  results = {}
  try:
    results = test_rolls(
      config_file, context, package_spec, args.projects or [])
  finally:
    if not results.get('success'):
      # Restore initial state. Since we could be running simulation tests
      # on other revisions, re-run them now as well.
      config_file.write(package_spec.dump())
      run_simulation_test(context.repo_root, package_spec, ['train'])

  if args.output_json:
    with open(args.output_json, 'w') as f:
      json.dump(
          results, f, default=default_json_encode, sort_keys=True, indent=4)

  return 0
