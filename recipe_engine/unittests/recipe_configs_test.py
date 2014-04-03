#!/usr/bin/python
# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides test coverage for common recipe configurations.

recipe config expectations are located in ../recipe_configs_test/*.expected

In training mode, this will loop over every config item in ../recipe_configs.py
crossed with every platform, and spit out the as_json() representation to
../recipe_configs_test

You must have 100% coverage of ../recipe_configs.py for this test to pass.
"""

import argparse
import multiprocessing
import os
import sys
from itertools import product, imap

import test_env  # "relative import" pylint: disable=W0403

from slave import recipe_loader
from slave import recipe_util

import coverage

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
SLAVE_DIR = os.path.abspath(os.path.join(SCRIPT_PATH, os.pardir))

COVERAGE = (lambda: coverage.coverage(
    include=[os.path.join(x, '*', '*config.py')
             for x in recipe_util.MODULE_DIRS()],
    data_file='.recipe_configs_test_coverage', data_suffix=True))()

def covered(fn, *args, **kwargs):
  COVERAGE.start()
  try:
    return fn(*args, **kwargs)
  finally:
    COVERAGE.stop()

RECIPE_MODULES = None
def init_recipe_modules():
  global RECIPE_MODULES
  RECIPE_MODULES = covered(recipe_loader.load_recipe_modules,
                           recipe_util.MODULE_DIRS())

from slave import recipe_config  # pylint: disable=F0401


def evaluate_configurations(args):
  mod_id, var_assignments = args
  mod = getattr(RECIPE_MODULES, mod_id)
  ctx = mod.CONFIG_CTX

  config_name = None
  try:
    make_item = lambda: covered(ctx.CONFIG_SCHEMA, **var_assignments)

    # Try ROOT_CONFIG_ITEM first. If it raises BadConf, then we can skip
    # this config.
    root_item = ctx.ROOT_CONFIG_ITEM
    if root_item:
      config_name = root_item.__name__
      try:
        result = covered(root_item, make_item())
        if result.complete():
          covered(result.as_jsonish)
      except recipe_config.BadConf, e:
        pass # This is a possibly expected failure mode.

    for config_name, fn in ctx.CONFIG_ITEMS.iteritems():
      if fn.NO_TEST or fn.IS_ROOT:
        continue
      try:
        result = covered(fn, make_item())
        if result.complete():
          covered(result.as_jsonish)
      except recipe_config.BadConf:
        pass  # This is a possibly expected failure mode.
    test_name = os.path.join(mod.__path__[0],
                             covered(ctx.TEST_NAME_FORMAT, var_assignments))
    print 'Evaluated', test_name
  except Exception, e:
    print 'Caught exception [%s] with args %s: %s' % (e, args, config_name)


def multiprocessing_init():
  init_recipe_modules()

  # HACK: multiprocessing doesn't work with atexit, so shim the exit functions
  # instead. This allows us to save exactly one coverage file per subprocess.
  # pylint: disable=W0212
  real_os_exit = multiprocessing.forking.exit
  def exitfn(code):
    COVERAGE.save()
    real_os_exit(code)
  multiprocessing.forking.exit = exitfn

  # This check mirrors the logic in multiprocessing.forking.exit
  if sys.platform != 'win32':
    # Even though multiprocessing.forking.exit is defined, it's not used in the
    # non-win32 version of multiprocessing.forking.Popen... *loss for words*
    os._exit = exitfn


def coverage_parallel_map(fn):
  combination_generator = (
    (mod_id, var_assignments)
    for mod_id, mod in RECIPE_MODULES.__dict__.iteritems()
      if mod_id[0] != '_' and mod.CONFIG_CTX
    for var_assignments in imap(dict, product(*[
      [(key_name, val) for val in vals]
      for key_name, vals in mod.CONFIG_CTX.VAR_TEST_MAP.iteritems()
    ]))
  )

  pool = multiprocessing.Pool(initializer=multiprocessing_init)
  try:
    return pool.map_async(fn, combination_generator).get(999999)
  finally:
    # necessary so that the subprocesses will write out their coverage due to
    # the hack in multiprocessing_init()
    pool.close()
    pool.join()


def main(argv):
  COVERAGE.erase()
  init_recipe_modules()

  p = argparse.ArgumentParser()
  p.add_argument('--train', action='store_true', help='deprecated')
  p.parse_args()

  coverage_parallel_map(evaluate_configurations)

  retcode = 0

  COVERAGE.combine()
  total_covered = COVERAGE.report()
  if total_covered != 100.0:
    print 'FATAL: Recipes configs are not at 100% coverage.'
    retcode = 2

  test_env.print_coverage_warning()

  return retcode


if __name__ == '__main__':
  sys.exit(main(sys.argv))
