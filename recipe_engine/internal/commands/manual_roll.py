# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Calculate the smallest possible recipes.cfg roll.

Prints changelist to stdout, extra info to stderr.

Exits 1 if no roll is found.
"""

from __future__ import print_function

import sys

from .autoroll.cmd import write_global_files_to_main_repo

from ..autoroll_impl.candidate_algorithm import get_roll_candidates


def add_arguments(parser):
  parser.set_defaults(func=main)


def main(args):
  original_spec = args.recipe_deps.main_repo.recipes_cfg_pb2

  # Fetch all remote changes locally, so we can compute metadata for them.
  for repo in args.recipe_deps.repos.itervalues():
    if repo.name == args.recipe_deps.main_repo_id:
      continue
    repo.backend.fetch(original_spec.deps[repo.name].branch)

  candidates, rejected, repos = get_roll_candidates(args.recipe_deps)

  if not candidates:
    print(
      'No roll found. Rejected %d invalid roll candidates.' %
      (len(rejected),), file=sys.stderr)
    return 1

  print(file=sys.stderr)
  print('recipes.cfg has been rolled, use `recipes.py test train` to train '
        'expectations.', file=sys.stderr)
  print(file=sys.stderr)
  print('Changelog:', file=sys.stderr)

  candidate = candidates[0]

  for pid, clist in candidate.changelist(repos).iteritems():
    print()
    print(pid+':')
    for commit in clist:
      print('  https://crrev.com/%s %s (%s)' % (
        commit.revision, commit.message_lines[0], commit.author_email
      ))

  write_global_files_to_main_repo(args.recipe_deps, candidate.repo_spec)

  return 0
