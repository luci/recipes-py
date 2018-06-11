# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile

from recipe_engine import fetch
from recipe_engine import package
from recipe_engine import package_io


@contextlib.contextmanager
def ensure_workdir(args):
  workdir_tempdir = False
  if not args.workdir:
    workdir_tempdir = True
    args.workdir = tempfile.mkdtemp(prefix='recipe_engine_remote_')
    logging.info('Created temporary workdir %s', args.workdir)

  try:
    yield
  finally:
    if workdir_tempdir:
      shutil.rmtree(args.workdir, ignore_errors=True)


def add_subparser(parser):
  helpstr = 'Invoke a recipe command from specified repo and revision.'
  remote_p = parser.add_parser(
      'remote', help=helpstr, description=helpstr)
  remote_p.add_argument(
      '--repository', required=True,
      help='URL of a git repository to fetch')
  remote_p.add_argument(
      '--revision',
      help=(
        'Git commit hash to check out; defaults to latest revision on master'
        ' (refs/heads/master)'
      ))
  remote_p.add_argument(
      '--workdir',
      type=os.path.abspath,
      help='The working directory of repo checkout')
  remote_p.add_argument(
      'remote_args', nargs='*',
      help='Arguments to pass to fetched repo\'s recipes.py')

  remote_p.set_defaults(
    bare_command=True,
    func=main,
  )


def main(_package_deps, args):
  with ensure_workdir(args):
    checkout_dir = os.path.join(args.workdir, 'checkout')
    revision = args.revision or 'refs/heads/master'
    backend = fetch.GitBackend(checkout_dir, args.repository)
    backend.checkout(revision)
    recipes_cfg = package_io.PackageFile(
        package_io.InfraRepoConfig().to_recipes_cfg(checkout_dir))
    cmd = [
        sys.executable,
        os.path.join(
            checkout_dir,
            recipes_cfg.read().recipes_path,
            'recipes.py'),
    ] + args.remote_args
    logging.info('Running %r', cmd)
    return subprocess.call(cmd)
