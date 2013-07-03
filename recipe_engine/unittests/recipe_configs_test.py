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

import json
import multiprocessing
import os
import sys
import unittest
from itertools import product, imap

import test_env  # pylint: disable=W0611,F0401

from slave import recipe_api
from slave import annotated_run

import coverage

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
SLAVE_DIR = os.path.abspath(os.path.join(SCRIPT_PATH, os.pardir))

COVERAGE = (lambda: coverage.coverage(
    include=[os.path.join(x, '*', '*config.py')
             for x in annotated_run.MODULE_DIRS],
    data_suffix=True))()

def covered(fn, *args, **kwargs):
  COVERAGE.start()
  try:
    return fn(*args, **kwargs)
  finally:
    COVERAGE.stop()

RECIPE_MODULES = None
def init_recipe_modules():
  global RECIPE_MODULES
  RECIPE_MODULES = covered(recipe_api.load_recipe_modules,
                           annotated_run.MODULE_DIRS)

from slave import recipe_configs_util  # pylint: disable=F0401

def get_expect_dir(mod):
  return os.path.join(mod.__path__[0], 'config.expected')


def evaluate_configurations(args):
  mod_id, var_assignments = args
  mod = getattr(RECIPE_MODULES, mod_id)
  expect_dir = get_expect_dir(mod)
  ctx = mod.CONFIG_CTX

  config_name = None
  try:
    file_name = os.path.join(expect_dir, ctx.TEST_FILE_FORMAT % var_assignments)
    ret = {}

    make_item = lambda: covered(ctx.CONFIG_SCHEMA, **var_assignments)

    # Try ROOT_CONFIG_ITEM first. If it raises BadConf, then we can skip
    # this config.
    root_item = ctx.ROOT_CONFIG_ITEM
    if root_item:
      config_name = root_item.__name__
      try:
        result = covered(root_item, make_item())
        if result.complete():
          ret[config_name] = result.as_jsonish()
      except recipe_configs_util.BadConf, e:
        return file_name, None, None

    for config_name, fn in ctx.CONFIG_ITEMS.iteritems():
      if fn.NO_TEST or fn.IS_ROOT:
        continue
      try:
        result = covered(fn, make_item())
        if result.complete():
          ret[config_name] = result.as_jsonish()
      except recipe_configs_util.BadConf, e:
        ret[config_name] = str(e)
    return file_name, (ctx.TEST_NAME_FORMAT % var_assignments), ret
  except Exception, e:
    print 'Caught exception [%s] with args %s: %s' % (e, args, config_name)


def train_from_tests(args):
  file_name, _, configuration_results = evaluate_configurations(args)
  if configuration_results is not None:
    if configuration_results:
      print 'Writing', file_name
      with open(file_name, 'wb') as f:
        json.dump(configuration_results, f, sort_keys=True, indent=2)
    else:
      print 'Empty', file_name

  if not configuration_results:  # None or {}
    if os.path.exists(file_name):
      os.unlink(file_name)
  return True


def load_tests(loader, _standard_tests, _pattern):
  """This method is invoked by unittest.main's automatic testloader."""
  def create_test_class(args):
    file_name, test_name_suffix, configuration_results = args
    if configuration_results is None:
      return

    json_expectation = {}
    if os.path.exists(file_name):
      with open(file_name, 'rb') as f:
        json_expectation = json.load(f)

    class RecipeConfigsTest(unittest.TestCase):
      def testNoLeftovers(self):
        """add_test_methods() should completely drain json_expectation."""
        self.assertEqual(json_expectation, {})

      @classmethod
      def add_test_methods(cls):
        for name, result in configuration_results.iteritems():
          def add_test(name, result, expected_result):
            def test_(self):
              self.assertEqual(result, expected_result)
            test_.__name__ += name
            setattr(cls, test_.__name__, test_)
          add_test(name, result, json_expectation.pop(name, {}))

    RecipeConfigsTest.add_test_methods()

    RecipeConfigsTest.__name__ += test_name_suffix
    return RecipeConfigsTest

  data = coverage_parallel_map(evaluate_configurations)

  suite = unittest.TestSuite()
  for test_class in map(create_test_class, data):
    if test_class is None:
      continue
    suite.addTest(loader.loadTestsFromTestCase(test_class))
  return suite


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

  for k, m in RECIPE_MODULES.__dict__.iteritems():
    if k[0] == '_':
      continue
    expect_dir = get_expect_dir(m)
    if not os.path.exists(expect_dir):
      os.makedirs(expect_dir)

  training = False
  is_help = False
  if '--help' in argv or '-h' in argv:
    print 'Pass --train to enter training mode.'
    print
    is_help = True
  if '--train' in argv:
    argv.remove('--train')
    training = True

  had_errors = False
  if training and not is_help:
    coverage_parallel_map(train_from_tests)

  retcode = 1 if had_errors else 0

  if not training:
    try:
      unittest.main()
    except SystemExit as e:
      retcode = e.code or retcode

  if not is_help:
    COVERAGE.combine()
    total_covered = COVERAGE.report()
    if total_covered != 100.0:
      print 'FATAL: Recipes configs are not at 100% coverage.'
      retcode = retcode or 2

  return retcode


if __name__ == '__main__':
  sys.exit(main(sys.argv))
