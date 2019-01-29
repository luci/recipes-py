#!/usr/bin/env vpython
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

import sys

# This is necessary to ensure that str literals are by-default assumed to hold
# utf-8. It also makes the implicit str(unicode(...)) act like
# unicode(...).encode('utf-8'), rather than unicode(...).encode('ascii') .
reload(sys)
sys.setdefaultencoding('UTF8')

import argparse
import logging
import os
import shutil
import subprocess
import tempfile

import urllib3.contrib.pyopenssl
urllib3.contrib.pyopenssl.inject_into_urllib3()

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from recipe_engine import common_args, package, package_io, util

from recipe_engine import run, test
from recipe_engine import analyze, autoroll, manual_roll, bundle, doc, lint


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

  analyze,
  autoroll,
  manual_roll,
  bundle,
  doc,
  lint,
]


def main():
  # Prune all evidence of VPython/VirtualEnv out of the environment. This means
  # that recipe engine 'unwraps' vpython VirtualEnv path/env manipulation.
  # Invocations of `python` from recipes should never inherit the recipe
  # engine's own VirtualEnv.

  # Set by VirtualEnv, no need to keep it.
  os.environ.pop('VIRTUAL_ENV', None)

  # Set by VPython, if recipes want it back they have to set it explicitly.
  os.environ.pop('PYTHONNOUSERSITE', None)

  # Look for "activate_this.py" in this path, which is installed by VirtualEnv.
  # This mechanism is used by vpython as well to sanitize VirtualEnvs from
  # $PATH.
  os.environ['PATH'] = os.pathsep.join([
    p for p in os.environ.get('PATH', '').split(os.pathsep)
    if not os.path.isfile(os.path.join(p, 'activate_this.py'))
  ])

  parser = argparse.ArgumentParser(
    description='Interact with the recipe system.')

  common_postprocess_func = common_args.add_common_args(parser)

  subp = parser.add_subparsers(dest='command')
  for module in _SUBCOMMANDS:
    module.add_subparser(subp)

  args = parser.parse_args()
  common_postprocess_func(parser, args)
  args.postprocess_func(parser, args)

  repo_root = package_io.InfraRepoConfig().from_recipes_cfg(args.package.path)

  try:
    # TODO(phajdan.jr): gracefully handle inconsistent deps when rolling.
    # This fails if the starting point does not have consistent dependency
    # graph. When performing an automated roll, it'd make sense to attempt
    # to automatically find a consistent state, rather than bailing out.
    # Especially that only some subcommands refer to package_deps.
    context = package.PackageContext.from_package_pb(
      repo_root, args.package.read())
    package_deps = package.PackageDeps.create(
        context, args.package, overrides=args.project_override)
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
    os._exit(1)

  if not isinstance(ret, int):
    if ret is None:
      ret = 0
    else:
      print >> sys.stderr, ret
      ret = 1
  sys.stdout.flush()
  sys.stderr.flush()
  os._exit(ret)
