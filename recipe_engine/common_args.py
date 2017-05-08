# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Common arguments to the various recipes.py subcommands.

This is in a separate file for recipes.py for testing purposes.
"""

import json
import logging
import os

from . import package_io

from . import env

import argparse  # this is vendored

from . import arguments_pb2

from google.protobuf import json_format as jsonpb


def add_common_args(parser):
  class ProjectOverrideAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      p = values.split('=', 2)
      if len(p) != 2:
        raise ValueError('Override must have the form: repo=path')
      project_id, path = p

      v = getattr(namespace, self.dest, None)
      if v is None:
        v = {}
        setattr(namespace, self.dest, v)

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
      type=package_type,
      help='Path to recipes.cfg of the recipe package to operate on'
        ', usually in infra/config/recipes.cfg')
  parser.add_argument(
      '--verbose', '-v', action='count',
      help='Increase logging verboisty')
  # TODO(phajdan.jr): Figure out if we need --no-fetch; remove if not.
  parser.add_argument(
      '--no-fetch', action='store_true',
      help='Disable automatic fetching')
  parser.add_argument('-O', '--project-override', metavar='ID=PATH',
      action=ProjectOverrideAction,
      help='Override a project repository path with a local one.')
  parser.add_argument(
      # Use 'None' as default so that we can recognize when none of the
      # bootstrap options were passed.
      '--use-bootstrap', action='store_true', default=None,
      help='Use bootstrap/bootstrap.py to create a isolated python virtualenv'
           ' with required python dependencies.')
  parser.add_argument(
      '--bootstrap-vpython-path', metavar='PATH',
      help='Specify the `vpython` executable path to use when bootstrapping ('
           'requires --use-bootstrap).')
  parser.add_argument(
      '--disable-bootstrap', action='store_false', dest='use_bootstrap',
      help='Disables bootstrap (see --use-bootstrap)')

  def operational_args_type(value):
    with open(value) as fd:
      return jsonpb.ParseDict(json.load(fd), arguments_pb2.Arguments())

  parser.set_defaults(
    operational_args=arguments_pb2.Arguments(),
    bare_command=False,  # don't call postprocess_func, don't use package_deps
    postprocess_func=lambda parser, args: None,
  )

  parser.add_argument(
      '--operational-args-path',
      dest='operational_args',
      type=operational_args_type,
      help='The path to an operational Arguments file. If provided, this file '
           'must contain a JSONPB-encoded Arguments protobuf message, and will '
           'be integrated into the runtime parameters.')

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

    if args.bare_command:
      # TODO(iannucci): this is gross, and only for the remote subcommand;
      # remote doesn't behave like ANY other commands. A way to solve this will
      # be to allow --package to take a remote repo and then simply remove the
      # remote subcommand entirely.
      if args.package is not None:
        parser.error('%s forbids --package' % args.command)
    else:
      if not args.package:
        parser.error('%s requires --package' % args.command)

  return post_process_args
