# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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


@contextlib.contextmanager
def ensure_workdir(args):
  workdir_tempdir = False
  if not args.workdir:
    workdir_tempdir = True
    args.workdir = tempfile.mkdtemp(prefix='recipe_engine_remote_run_')
    logging.info('Created temporary workdir %s', args.workdir)

  try:
    yield
  finally:
    if workdir_tempdir:
      shutil.rmtree(args.workdir, ignore_errors=True)


def main(args):
  with ensure_workdir(args):
    checkout_dir = os.path.join(args.workdir, 'checkout')
    fetch.ensure_git_checkout(
        args.repository, args.revision, checkout_dir, allow_fetch=True)
    recipes_cfg = package.ProtoFile(
        package.InfraRepoConfig().to_recipes_cfg(checkout_dir))
    cmd = [
        sys.executable,
        os.path.join(
            checkout_dir,
            recipes_cfg.read().recipes_path,
            'recipes.py'),
        'run'
    ] + args.run_args
    logging.info('Running %r', cmd)
    return subprocess.call(cmd)
