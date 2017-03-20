# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import json
import os
import subprocess
import sys

from . import package


NUL = open(os.devnull, 'w')

ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def default_json_encode(o):
  """Fallback for objects that JSON library can't serialize."""
  if isinstance(o, package.CommitInfo):
    return o.dump()

  return repr(o)


# This is the path within the recipes-py repo to the per-repo recipes.py script.
# Ideally we'd read this somehow from each candidate engine repo version, but
# for now assume it lives in a fixed location within the engine.
RECIPES_PY_REL_PATH = ('doc', 'recipes.py')

# These are the lines to look for in doc/recipes.py as well as the target repo's
# copy of that file. Any lines found between these lines will be replaced
# verbatim in the new recipes.py file.
EDIT_HEADER = '#### PER-REPO CONFIGURATION (editable) ####\n'
EDIT_FOOTER = '#### END PER-REPO CONFIGURATION ####\n'


def write_new_recipes_py(context, spec, repo_cfg_block):
  """Uses the doc/recipes.py script from the currently-checked-out version of
  the recipe_engine (in `context`) as a template, and writes it to the
  recipes_dir of the destination repo (also from `context`). Replaces the lines
  between the EDIT_HEADER and EDIT_FOOTER with the lines from repo_cfg_block,
  verbatim.

  Args:
    context (PackageContext) - The context of where to find the checked-out
      recipe_engine as well as where to put the new recipes.py.
    spec (PackageSpec) - The rolled spec (result of
      RollCandidate.get_rolled_spec())
    repo_cfg_block (list(str)) - The list of lines (including newlines)
      extracted from the repo's original recipes.py file (using the
      extract_repo_cfg_block function).
  """
  source_path = os.path.join(spec.deps['recipe_engine'].path,
                             *RECIPES_PY_REL_PATH)
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


def fetch(repo_root, package_spec):
  """
  Just fetch the recipes to the newly configured version.
  """
  # Use _local_ recipes.py, so that it checks out the pinned recipe engine,
  # rather than running recipe engine which may be at a different revision
  # than the pinned one.
  args = [
    sys.executable,
    os.path.join(repo_root, package_spec.recipes_path, 'recipes.py'),
    'fetch',
  ]
  subprocess.check_call(args, stdout=NUL, stderr=NUL)


def run_simulation_test(repo_root, package_spec, additional_args=None,
                        allow_fetch=False):
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
  ]
  if not allow_fetch:
    args.append('--no-fetch')
  args.append('simulation_test')
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

  repo_cfg_block = extract_repo_cfg_block(context)

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

    spec = candidate.get_rolled_spec()
    config_file.write(spec.dump())
    fetch(context.repo_root, package_spec)
    write_new_recipes_py(context, spec, repo_cfg_block)

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

      spec = candidate.get_rolled_spec()
      config_file.write(spec.dump())
      fetch(context.repo_root, package_spec)
      write_new_recipes_py(context, spec, repo_cfg_block)

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
      run_simulation_test(context.repo_root, package_spec, ['train'],
                          allow_fetch=True)

  if args.output_json:
    with open(args.output_json, 'w') as f:
      json.dump(
          results, f, default=default_json_encode, sort_keys=True, indent=4)

  return 0
