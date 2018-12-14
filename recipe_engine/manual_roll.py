# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import sys

from . import autoroll
from . import package
from . import package_io
from .autoroll_impl.candidate_algorithm import get_roll_candidates

from . import env


def add_subparser(parser):
  helpstr = (
    'Calculate the smallest possible recipes.cfg roll. '
    'Prints changelist to stdout, extra info to stderr. Exits 1 if no roll '
    'is found.'
  )
  manual_roll_p = parser.add_parser(
    'manual_roll', help=helpstr, description=helpstr)

  manual_roll_p.set_defaults(func=main)


def main(_package_deps, args):
  config_file = args.package
  repo_root = package_io.InfraRepoConfig().from_recipes_cfg(config_file.path)

  package_pb = config_file.read()

  context = package.PackageContext.from_package_pb(repo_root, package_pb)
  package_spec = package.PackageSpec.from_package_pb(context, package_pb)
  for repo_spec in package_spec.deps.values():
    repo_spec.fetch()

  candidates, rejected, repos = get_roll_candidates(context, package_spec)

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
    for c in clist:
      print('  https://crrev.com/%s %s (%s)' % (
        c.revision, c.message_lines[0], c.author_email
      ))

  autoroll.write_spec_to_disk(context, config_file, candidate.package_pb)

  return 0
