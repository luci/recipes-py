# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Common arguments to the various recipes.py subcommands.

This is in a separate file for recipes.py for testing purposes.
"""

import argparse
import collections
import json
import logging
import os

from . import package_io


def add_common_args(parser):
  class ProjectOverrideAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      p = values.split('=', 2)
      if len(p) != 2:
        raise ValueError('Override must have the form: repo=path')
      project_id, path = p

      v = getattr(namespace, self.dest)

      if v.get(project_id):
        raise ValueError('An override is already defined for [%s] (%s)' % (
                         project_id, v[project_id]))
      path = os.path.abspath(os.path.expanduser(path))
      if not os.path.isdir(path):
        raise ValueError('Override path [%s] is not a directory' % (path,))
      v[project_id] = path

  def package_type(value):
    if not os.path.isfile(value):
      raise argparse.ArgumentTypeError(
        'Given recipes config file %r does not exist.' % (value,))
    return package_io.PackageFile(value)

  parser.add_argument(
      '--package',
      type=package_type, required=True,
      help='Path to recipes.cfg of the recipe package to operate on'
        ', usually in infra/config/recipes.cfg')
  parser.add_argument(
      '--verbose', '-v', action='count',
      help='Increase logging verboisty')
  parser.add_argument('-O', '--project-override', metavar='ID=PATH',
      action=ProjectOverrideAction, default=collections.OrderedDict(),
      help='Override a project repository path with a local one.')
  parser.add_argument('--use-bootstrap', action='store_true', help='Deprecated')
  parser.add_argument('--disable-bootstrap', action='store_false',
                      dest='use_bootstrap', help='Deprecated')

  parser.set_defaults(
    postprocess_func=lambda parser, args: None,
  )

  def post_process_args(parser, args):
    # TODO(iannucci): We should always do logging.basicConfig() (probably with
    # logging.WARNING), even if no verbose is passed. However we need to be
    # careful as this could cause issues with spurious/unexpected output.
    # I think it's risky enough to do in a different CL.

    if args.verbose > 0:
      logging.basicConfig()
      logging.getLogger().setLevel(logging.INFO)
    if args.verbose > 1:
      logging.getLogger().setLevel(logging.DEBUG)

    try:
      spec = args.package.read()
    except Exception as ex:
      parser.error('bad --package %r: %s' % (args.package.path, ex.message,))

    extra = set(args.project_override).difference(set(spec.deps))
    if extra:
      parser.error(
        "attempted to override %r, which don't appear in recipes.cfg" %
        (extra,))

  return post_process_args
