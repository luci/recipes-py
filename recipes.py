#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

# This is necessary to ensure that str literals are by-default assumed to hold
# utf-8. It also makes the implicit str(unicode(...)) act like
# unicode(...).encode('utf-8'), rather than unicode(...).encode('ascii') .
reload(sys)
sys.setdefaultencoding('UTF8')

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from recipe_engine import env

import argparse  # this is vendored
from recipe_engine import arguments_pb2
from google.protobuf import json_format as jsonpb


from recipe_engine import fetch, lint_test, bundle, depgraph, autoroll
from recipe_engine import remote, refs, doc, test, run


# Each of these subcommands has a method:
#
#   def add_subparsers(argparse._SubParsersAction): ...
#
# which is expected to add a subparser by calling .add_parser on it. In
# addition, the add_subparsers method should call .set_defaults on the created
# sub-parser, and set the following values:
#   func (fn(package_deps, args)) - The function called if the sub command is
#     invoked.
#   postprocess_func (fn(parser, args)) - A validation/normalization function
#     which is called if the sub command is invoked. This function can
#     check/adjust the parsed args, calling parser.error if a problem is
#     encountered. This function is optional.
#   bare_command (bool) - This sub command's func will be called before parsing
#     package_deps. This is only used for the `remote` subcommand. See the
#     comment in add_common_args for why.
#
# Example:
#
#   def add_subparsers(parser):
#     sub = parser.add_parser("subcommand", help="a cool subcommand")
#     sub.add_argument("--cool_arg", help="it's gotta be cool")
#
#     def postprocess_args(parser, args):
#       if "cool" not in args.cool_arg:
#         parser.error("your cool_arg is not cool!")
#
#     sub.set_defaults(func=main)
#
#   def main(package_deps, args):
#     print args.cool_arg
_SUBCOMMANDS = [
  run,
  test,

  autoroll,
  bundle,
  depgraph,
  doc,
  fetch,
  lint_test,
  refs,
  remote,
]


def add_common_args(parser):
  from recipe_engine import package_io

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
      '--deps-path',
      type=os.path.abspath,
      help='Path where recipe engine dependencies will be extracted. Specify '
           '"-" to use a temporary directory for deps, which will be cleaned '
           'up on exit.')
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


def main():
  parser = argparse.ArgumentParser(
    description='Interact with the recipe system.')

  common_postprocess_func = add_common_args(parser)

  subp = parser.add_subparsers()
  for module in _SUBCOMMANDS:
    module.add_subparser(subp)

  args = parser.parse_args()
  common_postprocess_func(parser, args)
  args.postprocess_func(parser, args)

  # TODO(iannucci): We should always do logging.basicConfig() (probably with
  # logging.WARNING), even if no verbose is passed. However we need to be
  # careful as this could cause issues with spurious/unexpected output. I think
  # it's risky enough to do in a different CL.

  if args.verbose > 0:
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)
  if args.verbose > 1:
    logging.getLogger().setLevel(logging.DEBUG)

  # If we're bootstrapping, construct our bootstrap environment. If we're
  # using a custom deps path, install our enviornment there too.
  if args.use_bootstrap and not env.USING_BOOTSTRAP:
    logging.debug('Bootstrapping recipe engine through vpython...')

    bootstrap_env = os.environ.copy()
    bootstrap_env[env.BOOTSTRAP_ENV_KEY] = '1'

    cmd = [
        sys.executable,
        os.path.join(ROOT_DIR, 'bootstrap', 'bootstrap_vpython.py'),
    ]
    if args.bootstrap_vpython_path:
      cmd += ['--vpython-path', args.bootstrap_vpython_path]
    cmd += [
        '--',
        os.path.join(ROOT_DIR, 'recipes.py'),
    ] + sys.argv[1:]

    logging.debug('Running bootstrap command (cwd=%s): %s', ROOT_DIR, cmd)
    return subprocess.call(
        cmd,
        cwd=ROOT_DIR,
        env=bootstrap_env)

  # Standard recipe engine operation.
  return _real_main(args)


def _real_main(args):
  from recipe_engine import package

  if args.bare_command:
    return args.func(None, args)

  repo_root = package.InfraRepoConfig().from_recipes_cfg(args.package.path)

  try:
    # TODO(phajdan.jr): gracefully handle inconsistent deps when rolling.
    # This fails if the starting point does not have consistent dependency
    # graph. When performing an automated roll, it'd make sense to attempt
    # to automatically find a consistent state, rather than bailing out.
    # Especially that only some subcommands refer to package_deps.
    package_deps = package.PackageDeps.create(
        repo_root, args.package, allow_fetch=not args.no_fetch,
        deps_path=args.deps_path, overrides=args.project_override)
  except subprocess.CalledProcessError:
    # A git checkout failed somewhere. Return 2, which is the sign that this is
    # an infra failure, rather than a test failure.
    return 2

  return args.func(package_deps, args)


if __name__ == '__main__':
  # Use os._exit instead of sys.exit to prevent the python interpreter from
  # hanging on threads/processes which may have been spawned and not reaped
  # (e.g. by a leaky test harness).
  try:
    ret = main()
  except Exception as e:
    import traceback
    traceback.print_exc(file=sys.stderr)
    print >> sys.stderr, 'Uncaught exception (%s): %s' % (type(e).__name__, e)
    sys.exit(1)

  if not isinstance(ret, int):
    if ret is None:
      ret = 0
    else:
      print >> sys.stderr, ret
      ret = 1
  sys.stdout.flush()
  sys.stderr.flush()
  os._exit(ret)
