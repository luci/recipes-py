# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import copy
import json
import logging
import os
import subprocess
import sys
import time

from collections import namedtuple

from . import package
from . import package_io
from .autoroll_impl.candidate_algorithm import get_roll_candidates


LOGGER = logging.getLogger(__name__)

ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


# This is the path within the recipes-py repo to the per-repo recipes.py script.
# Ideally we'd read this somehow from each candidate engine repo version, but
# for now assume it lives in a fixed location within the engine.
RECIPES_PY_REL_PATH = ('doc', 'recipes.py')

# These are the lines to look for in doc/recipes.py as well as the target repo's
# copy of that file. Any lines found between these lines will be replaced
# verbatim in the new recipes.py file.
EDIT_HEADER = '#### PER-REPO CONFIGURATION (editable) ####\n'
EDIT_FOOTER = '#### END PER-REPO CONFIGURATION ####\n'


def write_new_recipes_py(context, pspec, repo_cfg_block):
  """Uses the doc/recipes.py script from the currently-checked-out version of
  the recipe_engine (in `context`) as a template, and writes it to the
  recipes_dir of the destination repo (also from `context`). Replaces the lines
  between the EDIT_HEADER and EDIT_FOOTER with the lines from repo_cfg_block,
  verbatim.

  Args:
    context (PackageContext) - The context of where to find the checked-out
      recipe_engine as well as where to put the new recipes.py.
    spec (PackageSpec) - The current (rolled) PackageSpec spec.
    repo_cfg_block (list(str)) - The list of lines (including newlines)
      extracted from the repo's original recipes.py file (using the
      extract_repo_cfg_block function).
  """
  engine_root = pspec.deps['recipe_engine'].repo_root(context)
  source_path = os.path.join(engine_root, *RECIPES_PY_REL_PATH)
  dest_path = os.path.join(context.recipes_dir, 'recipes.py')
  with open(source_path, 'rb') as source:
    with open(dest_path, 'wb') as dest:
      for line in source:
        dest.write(line)
        if line == EDIT_HEADER:
          break
      dest.writelines(repo_cfg_block)
      for line in source:
        if line == EDIT_FOOTER:
          dest.write(line)
          break
      dest.writelines(source)
  if sys.platform != 'win32':
    os.chmod(dest_path, os.stat(dest_path).st_mode|0111)


def extract_repo_cfg_block(context):
  """Extracts the lines between EDIT_HEADER and EDIT_FOOTER from the
  to-be-autorolled-repo's recipes.py file.

  Args:
    context (PackageContext) - The context of where to find the repo's current
      recipes.py file.

  Returns list(str) - The list of lines (including newlines) which occur between
    the EDIT_HEADER and EDIT_FOOTER in the repo's recipes.py file.
  """
  recipes_py_path = os.path.join(context.recipes_dir, 'recipes.py')
  block = []
  with open(recipes_py_path, 'rb') as f:
    in_section = False
    for line in f:
      if not in_section and line == EDIT_HEADER:
        in_section = True
      elif in_section:
        if line == EDIT_FOOTER:
          break
        block.append(line)
  if not block:
    raise ValueError('unable to find configuration section in %r' %
                     (recipes_py_path,))
  return block


def write_spec_to_disk(context, repo_cfg_block, config_file, spec_pb):
  LOGGER.info('writing: %s', package_io.dump(spec_pb))
  pspec = package.PackageSpec.from_package_pb(context, spec_pb)

  config_file.write(spec_pb)
  fetch(context.repo_root, spec_pb.recipes_path)
  write_new_recipes_py(context, pspec, repo_cfg_block)


def fetch(repo_root, recipes_path):
  """
  Just fetch the recipes to the newly configured version.
  """
  # Use _local_ recipes.py, so that it checks out the pinned recipe engine,
  # rather than running recipe engine which may be at a different revision
  # than the pinned one.
  args = [
    sys.executable,
    os.path.join(repo_root, recipes_path, 'recipes.py'),
    # Invoked recipes.py should not re-bootstrap (to avoid issues on bots).
    '--disable-bootstrap',
    'fetch',
  ]
  subprocess.check_call(args)


def run_simulation_test(repo_root, recipes_path, additional_args=None):
  """
  Runs recipe simulation test for given package.

  Returns a tuple of exit code and output.
  """
  # Use _local_ recipes.py, so that it checks out the pinned recipe engine,
  # rather than running recipe engine which may be at a different revision
  # than the pinned one.
  args = [
    sys.executable,
    os.path.join(repo_root, recipes_path, 'recipes.py'),
    # Invoked recipes.py should not re-bootstrap (to avoid issues on bots).
    '--disable-bootstrap',
    '--no-fetch',
    'test',
  ]
  if additional_args:
    args.extend(additional_args)
  p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = p.communicate()
  rc = p.returncode
  return rc, output


def process_candidates(repo_cfg_block, candidates, repos, context, config_file,
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

    write_spec_to_disk(context, repo_cfg_block, config_file,
                       candidate.package_pb)

    rc, output = run_simulation_test(
      context.repo_root, candidate.package_pb.recipes_path, ['run'])
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

      write_spec_to_disk(context, repo_cfg_block, config_file,
                         candidate.package_pb)

      rc, output = run_simulation_test(
          context.repo_root, candidate.package_pb.recipes_path, ['train'])
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


def test_rolls(repo_cfg_block, config_file, context, package_spec,
               verbose_json):
  candidates, rejected_candidates, repos = get_roll_candidates(
    context, package_spec)
  trivial, picked_roll_details, roll_details = process_candidates(
    repo_cfg_block, candidates, repos, context, config_file, verbose_json)

  ret = {
    'success': bool(picked_roll_details),
    'trivial': trivial,
    'roll_details': roll_details,
    'picked_roll_details': picked_roll_details,
    'rejected_candidates_count': len(rejected_candidates),
  }
  if verbose_json:
    ret['rejected_candidate_specs'] = [
      package_io.dump_obj(c.package_pb) for c in rejected_candidates]
  return ret


def main(args, repo_root, config_file):
  package_pb = config_file.read()

  context = package.PackageContext.from_package_pb(
    repo_root, package_pb, allow_fetch=not args.no_fetch)
  package_spec = package.PackageSpec.from_package_pb(context, package_pb)
  for repo_spec in package_spec.deps.values():
    repo_spec.fetch()

  repo_cfg_block = extract_repo_cfg_block(context)

  results = {}
  try:
    results = test_rolls(
      repo_cfg_block, config_file, context, package_spec, args.verbose_json)
  finally:
    if not results.get('success'):
      # Restore initial state. Since we could be running simulation tests
      # on other revisions, re-run them now as well.
      write_spec_to_disk(context, repo_cfg_block, config_file, package_pb)
      run_simulation_test(repo_root, package_spec.recipes_path, ['train'])

  if args.output_json:
    with open(args.output_json, 'w') as f:
      json.dump(results, f, sort_keys=True, indent=2)

  return 0
