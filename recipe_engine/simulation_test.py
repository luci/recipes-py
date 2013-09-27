#!/usr/bin/python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides test coverage for individual recipes.

Recipe tests are located in ../recipes_test/*.py.

Each py file's splitext'd name is expected to match a recipe in ../recipes/*.py.

Each test py file contains one or more test functions:
  * A test function's name ends with '_test' and takes an instance of TestAPI
    as its only parameter.
  * The test should return a dictionary with any of the following keys:
    * factory_properties
    * build_properties
    * test_data
      * test_data's value should be a dictionary in the form of
        {stepname -> (retcode, json_data)}
      * Since the test doesn't run any steps, test_data allows you to simulate
        return values for particular steps.

Once your test methods are set up, run `recipes_test.py --train`. This will
take your tests and simulate what steps would have run, given the test inputs,
and will record them as JSON into files of the form:
  ../recipes_test/<recipe_name>.<test_name>.expected

If those files look right, make sure they get checked in with your changes.

When this file runs as a test (i.e. as `recipes_test.py`), it will re-evaluate
the recipes using the test function input data and compare the result to the
values recorded in the .expected files.

Additionally, this test cannot pass unless every recipe in ../recipes has 100%
code coverage when executed via the tests in ../recipes_test.
"""

import contextlib
import json
import os
import sys

from glob import glob

import test_env  # pylint: disable=F0401,W0611

import coverage

import common.python26_polyfill  # pylint: disable=W0611
import unittest

from common import annotator
from slave import recipe_util
from slave import annotated_run
from slave import recipe_loader

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
ROOT_PATH = os.path.abspath(os.path.join(SCRIPT_PATH, os.pardir, os.pardir,
                                         os.pardir))
SLAVE_DIR = os.path.join(ROOT_PATH, 'slave', 'fake_slave', 'build')

BASE_DIRS = recipe_util.BASE_DIRS
COVERAGE = None


@contextlib.contextmanager
def cover():
  COVERAGE.start()
  try:
    yield
  finally:
    COVERAGE.stop()

def expected_for(recipe_path, test_name):
  root, name = os.path.split(recipe_path)
  name = os.path.splitext(name)[0]
  expect_path = os.path.join(root, '%s.expected' % name)
  if not os.path.isdir(expect_path):
    os.makedirs(expect_path)
  return os.path.join(expect_path, test_name+'.json')


def exec_test_file(recipe_path):
  gvars = {}
  with cover():
    execfile(recipe_path, gvars)
    try:
      test_api = recipe_loader.CreateTestApi(gvars['DEPS'])
      gen = gvars['GenTests'](test_api)
    except Exception, e:
      print "Caught exception while processing %s: %s" % (recipe_path, e)
      raise
  try:
    while True:
      with cover():
        test_data = next(gen)
      yield test_data
  except StopIteration:
    pass
  except:
    print 'Exception while processing "%s"!' % recipe_path
    raise


def execute_test_case(test_data, recipe_path, recipe_name):
  try:
    props = test_data.properties
    props['recipe'] = recipe_name

    stream = annotator.StructuredAnnotationStream(stream=open(os.devnull, 'w'))

    def api(*args, **kwargs):
      return recipe_loader.CreateRecipeApi(test_data=test_data, *args, **kwargs)

    with cover():
      step_data = annotated_run.run_steps(
        stream, props, props, api, test_data).steps_ran.values()
      return [s.step for s in step_data]
  except:
    print 'Exception while processing "%s"!' % recipe_path
    raise


def train_from_tests((recipe_path, recipe_name)):
  for path in glob(expected_for(recipe_path, '*')):
    os.unlink(path)

  for test_data in exec_test_file(recipe_path):
    steps = execute_test_case(test_data, recipe_path, recipe_name)
    expected_path = expected_for(recipe_path, test_data.name)
    print 'Writing', expected_path
    with open(expected_path, 'wb') as f:
      json.dump(steps, f, sort_keys=True, indent=2, separators=(',', ': '))

  return True


def load_tests(loader, _standard_tests, _pattern):
  """This method is invoked by unittest.main's automatic testloader."""
  def create_test_class((recipe_path, recipe_name)):
    class RecipeTest(unittest.TestCase):
      @classmethod
      def add_test_methods(cls):
        for test_data in exec_test_file(recipe_path):
          expected_path = expected_for(recipe_path, test_data.name)
          def add_test(test_data, expected_path, recipe_name):
            def test_(self):
              steps = execute_test_case(test_data, recipe_path, recipe_name)
              # Roundtrip json to get same string encoding as load
              steps = json.loads(json.dumps(steps))
              with open(expected_path, 'rb') as f:
                expected = json.load(f)
              self.assertEqual(steps, expected)
            test_.__name__ += test_data.name
            setattr(cls, test_.__name__, test_)
          add_test(test_data, expected_path, recipe_name)

    RecipeTest.add_test_methods()

    RecipeTest.__name__ += '_for_%s' % (
      os.path.splitext(os.path.basename(recipe_path))[0])
    return RecipeTest

  suite = unittest.TestSuite()
  for test_class in map(create_test_class, recipe_loader.loop_over_recipes()):
    suite.addTest(loader.loadTestsFromTestCase(test_class))
  return suite


def main(argv):
  if not os.path.exists(SLAVE_DIR):
    os.makedirs(SLAVE_DIR)

  os.chdir(SLAVE_DIR)

  training = False
  is_help = False
  if '--help' in argv or '-h' in argv:
    print 'Pass --train to enter training mode.'
    print
    is_help = True
  if '--train' in argv:
    argv.remove('--train')
    training = True
  if '--external' in argv:
    argv.remove('--external')
    BASE_DIRS[:] = [d for d in BASE_DIRS if 'internal' not in d]
  global COVERAGE
  COVERAGE = coverage.coverage(
    include=(
      [os.path.join(x, '*') for x in recipe_util.RECIPE_DIRS()] +
      [os.path.join(x, '*', '*api.py') for x in recipe_util.MODULE_DIRS()]
    )
  )

  had_errors = False
  if training and not is_help:
    for result in map(train_from_tests, recipe_loader.loop_over_recipes()):
      had_errors = had_errors or result
      if had_errors:
        break

  retcode = 1 if had_errors else 0

  if not training:
    try:
      unittest.main()
    except SystemExit as e:
      retcode = e.code or retcode

  if not is_help:
    total_covered = COVERAGE.report()
    if total_covered != 100.0:
      print 'FATAL: Recipes are not at 100% coverage.'
      retcode = retcode or 2

  if training:
    test_env.print_coverage_warning()

  return retcode


if __name__ == '__main__':
  sys.exit(main(sys.argv))
