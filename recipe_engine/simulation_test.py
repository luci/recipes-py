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

import collections
import contextlib
import json
import os
import sys
import unittest

from glob import glob

import test_env  # pylint: disable=W0611

import coverage

from common import annotator

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
ROOT_PATH = os.path.abspath(os.path.join(SCRIPT_PATH, os.pardir, os.pardir,
                                         os.pardir))
SLAVE_DIR = os.path.join(ROOT_PATH, 'slave', 'fake_slave', 'build')
INTERNAL_DIR = os.path.join(ROOT_PATH, os.pardir, 'build_internal')
BASE_DIRS = {
    'Public': os.path.dirname(SCRIPT_PATH),
    'Internal': os.path.join(INTERNAL_DIR, 'scripts', 'slave'),
}
# TODO(iannucci): Check for duplicate recipe names when we have more than one
# base_dir

COVERAGE = coverage.coverage(
    include=([os.path.join(x, 'recipes', '*') for x in BASE_DIRS.values()]+
             [os.path.join(SCRIPT_PATH, os.pardir, 'recipe_modules',
                           '*', 'api.py')])
)


@contextlib.contextmanager
def cover():
  COVERAGE.start()
  try:
    yield
  finally:
    COVERAGE.stop()

with cover():
  from slave import annotated_run
  from slave import recipe_api

class TestAPI(object):
  @staticmethod
  def properties_generic(**kwargs):
    """
    Merge kwargs into a typical buildbot properties blob, and return the blob.
    """
    ret = {
        'blamelist': 'cool_dev1337@chromium.org,hax@chromium.org',
        'blamelist_real': ['cool_dev1337@chromium.org', 'hax@chromium.org'],
        'buildername': 'TestBuilder',
        'buildnumber': 571,
        'mastername': 'chromium.testing.master',
        'slavename': 'TestSlavename',
        'workdir': '/path/to/workdir/TestSlavename',
    }
    ret.update(kwargs)
    return ret

  @staticmethod
  def properties_scheduled(**kwargs):
    """
    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a chrome/trunk svn scheduler, and return the blob.
    """
    ret = TestAPI.properties_generic(
        branch='TestBranch',
        project='',
        repository='svn://svn-mirror.golo.chromium.org/chrome/trunk',
        revision='204787',
    )
    ret.update(kwargs)
    return ret

  @staticmethod
  def properties_tryserver(**kwargs):
    """
    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a rietveld tryjob on the tryserver, and return the blob.
    """
    ret = TestAPI.properties_generic(
        branch='',
        issue=12853011,
        patchset=1,
        project='chrome',
        repository='',
        requester='commit-bot@chromium.org',
        revision='HEAD',
        rietveld='https://chromiumcodereview.appspot.com',
        root='src',
    )
    ret.update(kwargs)
    return ret


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
      gen = gvars['GenTests'](TestAPI())
    except Exception, e:
      print "Caught exception while processing %s: %s" % (recipe_path, e)
      raise
  try:
    while True:
      with cover():
        name, test_data = next(gen)
      yield name, test_data
  except StopIteration:
    pass


def execute_test_case(test_data, recipe_path):
  test_data = test_data.copy()
  props = test_data.pop('properties', {}).copy()
  td = test_data.pop('step_mocks', {}).copy()
  props['recipe'] = os.path.basename(os.path.splitext(recipe_path)[0])

  mock_data = test_data.pop('mock', {})
  mock_data = collections.defaultdict(lambda: collections.defaultdict(dict),
                                      mock_data)

  assert not test_data, 'Got leftover test data: %s' % test_data

  stream = annotator.StructuredAnnotationStream(stream=open(os.devnull, 'w'))

  def api(*args, **kwargs):
    return recipe_api.CreateRecipeApi(mocks=mock_data, *args, **kwargs)

  with cover():
    try:
      step_data = annotated_run.run_steps(
        stream, props, props, api, td).steps_ran.values()
      return [s.step for s in step_data]
    except:
      print 'Exception while processing "%s"!' % recipe_path
      raise


def train_from_tests(recipe_path):
  for path in glob(expected_for(recipe_path, '*')):
    os.unlink(path)

  for name, test_data in exec_test_file(recipe_path):
    steps = execute_test_case(test_data, recipe_path)
    expected_path = expected_for(recipe_path, name)
    print 'Writing', expected_path
    with open(expected_path, 'w') as f:
      f.write('[')
      first = True
      for step in steps:
        f.write(('' if first else '\n  },')+'\n  {')
        first_dict_item = True
        for key, value in sorted(step.items(), key=lambda x: x[0]):
          f.write(('' if first_dict_item else ',')+'\n   ')
          f.write('"%s": ' % key)
          json.dump(value, f, sort_keys=True)
          first_dict_item = False
        first = False
      f.write('\n  }\n]')

  return True


def load_tests(loader, _standard_tests, _pattern):
  """This method is invoked by unittest.main's automatic testloader."""
  def create_test_class(recipe_path):
    class RecipeTest(unittest.TestCase):
      @classmethod
      def add_test_methods(cls):
        for name, test_data in exec_test_file(recipe_path):
          expected_path = expected_for(recipe_path, name)
          def add_test(test_data, expected_path):
            def test_(self):
              steps = execute_test_case(test_data, recipe_path)
              # Roundtrip json to get same string encoding as load
              steps = json.loads(json.dumps(steps))
              with open(expected_path, 'r') as f:
                expected = json.load(f)
              self.assertEqual(steps, expected)
            test_.__name__ += name
            setattr(cls, test_.__name__, test_)
          add_test(test_data, expected_path)

    RecipeTest.add_test_methods()

    RecipeTest.__name__ += '_for_%s' % (
      os.path.splitext(os.path.basename(recipe_path))[0])
    return RecipeTest

  suite = unittest.TestSuite()
  for test_class in map(create_test_class, loop_over_recipes()):
    suite.addTest(loader.loadTestsFromTestCase(test_class))
  return suite


def loop_over_recipes():
  for _name, path in BASE_DIRS.iteritems():
    recipe_dir = os.path.join(path, 'recipes')
    for root, _dirs, files in os.walk(recipe_dir):
      for recipe in (f for f in files if f.endswith('.py') and f[0] != '_'):
        recipe_path = os.path.join(root, recipe)
        with cover():
          # Force this file into coverage, even if there's no test for it.
          execfile(recipe_path, {})
        yield recipe_path


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

  had_errors = False
  if training and not is_help:
    for result in map(train_from_tests, loop_over_recipes()):
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

  return retcode


if __name__ == '__main__':
  sys.exit(main(sys.argv))
