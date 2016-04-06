# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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


def run_simulation_test(package, additional_args=None):
  """
  Runs recipe simulation test for given package.

  Returns a tuple of exit code and output.
  """
  args = [
    sys.executable,
    os.path.join(ROOT_DIR, 'recipes.py'),
    '--package', package,
    'simulation_test',
  ]
  if additional_args:
    args.extend(additional_args)
  p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = p.communicate()
  rc = p.returncode
  return rc, output


def test_rolls(args, config_file, context, package_spec):
  roll_details = []

  success = False
  trivial = None
  picked_roll_details = None

  print('finding roll candidates...')

  root_spec = package.RootRepoSpec(config_file)
  candidates, rejected_candidates = package_spec.roll_candidates(
      root_spec, context)

  # Fill basic information about all the candidates. In later loops
  # we exit early depending on test results.
  for i, candidate in enumerate(candidates):
    roll_details.append({
      'spec': str(candidate.get_rolled_spec().dump()),
      'diff': candidate.get_diff(),
      'commit_infos': candidate.get_commit_infos(),
    })

  rejected_candidates_details = []
  for candidate in rejected_candidates:
    rejected_candidates_details.append({
        'spec': str(candidate.get_rolled_spec().dump()),
        'commit_infos': candidate.get_commit_infos(),
    })

  print('looking for a trivial roll...')

  # Process candidates biggest first. If the roll is trivial, we want
  # the maximal one, e.g. to jump over some reverts, or include fixes
  # landed later for incompatible API changes.
  for i, candidate in enumerate(candidates):
    print('  processing candidate #%d... ' % (i + 1), end='')

    config_file.write(candidate.get_rolled_spec().dump())
    rc, output = run_simulation_test(args.package)
    roll_details[i]['recipes_simulation_test'] = {
      'output': output,
      'rc': rc,
    }

    if rc == 0:
      print('SUCCESS!')
      success = True
      trivial = True
      picked_roll_details = roll_details[i]
      break
    else:
      print('FAILED')

  if not success:
    print('looking for a nontrivial roll...')

    # Process candidates smallest first. If the roll is going to change
    # expectations, it should be minimal to avoid pulling too many unrelated
    # changes.
    for i, candidate in reversed(list(enumerate(candidates))):
      print('  processing candidate #%d... ' % (i + 1), end='')

      config_file.write(candidate.get_rolled_spec().dump())

      rc, output = run_simulation_test(args.package, ['train'])
      roll_details[i]['recipes_simulation_test_train'] = {
        'output': output,
        'rc': rc,
      }

      if rc == 0:
        print('SUCCESS!')
        success = True
        trivial = False
        picked_roll_details = roll_details[i]
        break
      else:
        print('FAILED')

  return {
    'success': success,
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
    results = test_rolls(args, config_file, context, package_spec)
  finally:
    if not results.get('success'):
      # Restore initial state. Since we could be running simulation tests
      # on other revisions, re-run them now as well.
      config_file.write(package_spec.dump())
      run_simulation_test(args.package, ['train'])

  if args.output_json:
    with open(args.output_json, 'w') as f:
      json.dump(
          results, f, default=default_json_encode, sort_keys=True, indent=4)

  return 0
