# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import json
import logging
import os
import shutil
import subprocess
import sys

from . import package
from . import package_io
from .autoroll_impl.candidate_algorithm import get_roll_candidates

from . import env

import argparse  # this is vendored


LOGGER = logging.getLogger(__name__)

ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

IS_WIN = sys.platform.startswith(('win', 'cygwin'))
VPYTHON = 'vpython' + ('.bat' if IS_WIN else '')
GIT = 'git' + ('.bat' if IS_WIN else '')

def write_spec_to_disk(context, config_file, spec_pb):
  LOGGER.info('writing: %s', package_io.dump(spec_pb))

  config_file.write(spec_pb)
  pspec = package.PackageSpec.from_package_pb(context, spec_pb)
  engine_root = pspec.deps['recipe_engine'].repo_root(context)

  engine_spec = spec_pb.deps['recipe_engine']
  if not engine_spec.url.startswith('file://'):
    # Update recipe_engine to the correct version and copy its matching
    # recipes.py bootstrap script.
    subprocess.check_call([
      GIT, '-C', engine_root, 'checkout', engine_spec.revision])

  if os.path.isfile(os.path.join(engine_root, 'recipes.py')):
    shutil.copy(
      os.path.join(engine_root, 'recipes.py'),
      os.path.join(context.recipes_dir, 'recipes.py')
    )
  else:
    # TODO(iannucci): Remove this path when new engine is rolled everywhere.
    # crbug.com/913102
    shutil.copy(
      os.path.join(engine_root, 'doc', 'recipes.py'),
      os.path.join(context.recipes_dir, 'recipes.py')
    )


def run_simulation_test(repo_root, recipes_path, additional_args=None):
  """
  Runs recipe simulation test for given package.

  Returns a tuple of exit code and output.
  """
  # Use _local_ recipes.py, so that it checks out the pinned recipe engine,
  # rather than running recipe engine which may be at a different revision
  # than the pinned one.
  args = [
    VPYTHON, os.path.join(repo_root, recipes_path, 'recipes.py'), 'test',
  ]
  if additional_args:
    args.extend(additional_args)
  p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = p.communicate()
  rc = p.returncode
  return rc, output


def regen_docs(repo_root, recipes_path):
  """
  Regenerates README.recipes.md.

  Raises a CalledProcessError on failure.
  """
  # Use _local_ recipes.py, so that it checks out the pinned recipe engine,
  # rather than running recipe engine which may be at a different revision
  # than the pinned one.
  subprocess.check_call([
    VPYTHON, os.path.join(repo_root, recipes_path, 'recipes.py'), 'doc',
    '--kind', 'gen',
  ])


def process_candidates(candidates, repos, context, config_file,
                       verbose_json):
  """

  Args:
    candidates (list(RollCandidate)) - A list of valid (self-consistent) roll
      candidates to try in least-changes to most-changes order.
    repos (dict(project_id, CommitList)) - A repos dictionary suitable for
      invoking RollCandidate.changelist().
    context (PackageContext)
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
      'spec': package_io.dump_obj(candidate.package_pb),
      'commit_infos': {
        pid: [{
          'author_email': c.author_email,
          'message_lines': (
            c.message_lines if verbose_json else c.message_lines[:1]
          ),
          'revision': c.revision,
        } for c in clist]
        for pid, clist in candidate.changelist(repos).iteritems()},
    })

  # Process candidates biggest first. If the roll is trivial, we want
  # the maximal one, e.g. to jump over some reverts, or include fixes
  # landed later for incompatible API changes.
  for i, candidate in enumerate(candidates):
    print('  processing candidate #%d... ' % (i + 1), end='')

    write_spec_to_disk(context, config_file, candidate.package_pb)

    rc, output = run_simulation_test(
      context.repo_root, candidate.package_pb.recipes_path, ['run'])
    if verbose_json:
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

      write_spec_to_disk(context, config_file, candidate.package_pb)

      rc, output = run_simulation_test(
          context.repo_root, candidate.package_pb.recipes_path,
          ['train', '--no-docs'])
      if verbose_json:
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


def test_rolls(config_file, context, package_spec,
               verbose_json):
  candidates, rejected_candidates, repos = get_roll_candidates(
    context, package_spec)

  roll_details = []
  picked_roll_details = None
  trivial = True
  if candidates:
    trivial, picked_roll_details, roll_details = process_candidates(
      candidates, repos, context, config_file, verbose_json)

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
      package_io.dump_obj(c.package_pb) for c in rejected_candidates]
  return ret


def add_subparser(parser):
  helpstr = 'Roll dependencies of a recipe package forward.'
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


def main(_package_deps, args):
  config_file = args.package
  repo_root = package_io.InfraRepoConfig().from_recipes_cfg(config_file.path)

  package_pb = config_file.read()

  context = package.PackageContext.from_package_pb(repo_root, package_pb)
  package_spec = package.PackageSpec.from_package_pb(context, package_pb)
  for repo_spec in package_spec.deps.values():
    repo_spec.fetch()

  results = {}
  try:
    results = test_rolls(
      config_file, context, package_spec, args.verbose_json)
  finally:
    if not results.get('success'):
      # Restore initial state. Since we could be running simulation tests
      # on other revisions, re-run them now as well.
      write_spec_to_disk(context, config_file, package_pb)
      run_simulation_test(repo_root, package_spec.recipes_path, ['train'])
    elif results.get('picked_roll_details'):
      # Success! We need to regen docs now.
      regen_docs(context.repo_root, package_spec.recipes_path)

  if args.output_json:
    with args.output_json:
      json.dump(results, args.output_json, sort_keys=True, indent=2)

  return 0
