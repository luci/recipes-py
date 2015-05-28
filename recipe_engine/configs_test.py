# Copyright 2013-2015 The Chromium Authors. All rights reserved.
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
import traceback
from itertools import product, imap

from . import loader
from . import config

import coverage

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
SLAVE_DIR = os.path.abspath(os.path.join(SCRIPT_PATH, os.pardir))

UNIVERSE = None
COVERAGE = None

def covered(fn, *args, **kwargs):
  COVERAGE.start()
  try:
    return fn(*args, **kwargs)
  finally:
    COVERAGE.stop()


def load_recipe_modules():
  modules = {}
  for modpath in UNIVERSE.loop_over_recipe_modules():
    # That's right, we're using the path as the local name! The local
    # name really could be anything unique, we don't use it.
    modules[modpath] = UNIVERSE.load(loader.PathDependency(
        modpath, local_name=modpath, base_path=os.curdir, universe=UNIVERSE))
  return modules


RECIPE_MODULES = None
def init_recipe_modules():
  global RECIPE_MODULES
  RECIPE_MODULES = covered(load_recipe_modules)


def evaluate_configurations(args):
  mod_id, var_assignments = args
  mod = RECIPE_MODULES[mod_id]
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
      except config.BadConf, e:
        pass # This is a possibly expected failure mode.

    for config_name, fn in ctx.CONFIG_ITEMS.iteritems():
      if fn.NO_TEST or fn.IS_ROOT:
        continue
      try:
        result = covered(fn, make_item())
        if result.complete():
          covered(result.as_jsonish)
      except config.BadConf:
        pass  # This is a possibly expected failure mode.
    return True
  except Exception as e:
    print ('Caught unknown exception [%s] for config name [%s] for module '
           '[%s] with args %s') % (e, config_name, mod_id, var_assignments)
    traceback.print_exc()
    return False


def multiprocessing_init():
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
    for mod_id, mod in RECIPE_MODULES.iteritems()
    if mod.CONFIG_CTX
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


def main(universe):
  global UNIVERSE
  global COVERAGE
  UNIVERSE = universe
  COVERAGE = coverage.coverage(
    include=[os.path.join(x, '*', '*config.py')
             for x in UNIVERSE.module_dirs],
    data_file='.recipe_configs_test_coverage', data_suffix=True)
  COVERAGE.erase()
  init_recipe_modules()

  success = all(coverage_parallel_map(evaluate_configurations))

  COVERAGE.combine()
  total_covered = COVERAGE.report()
  all_covered = total_covered == 100.0

  if not success:
    print 'FATAL: Some recipe configuration(s) failed'
  if not all_covered:
    print 'FATAL: Recipes configs are not at 100% coverage.'

  return 1 if (not success or not all_covered) else 0


if __name__ == '__main__':
  sys.exit(main())
