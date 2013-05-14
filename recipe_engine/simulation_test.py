#!/usr/bin/python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import json
import os
import sys
import unittest

from glob import glob

import test_env  # pylint: disable=W0611

import coverage

from common import annotator
from slave import annotated_run
from slave import recipe_util

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
ROOT_PATH = os.path.abspath(os.path.join(SCRIPT_PATH, os.pardir, os.pardir,
                                         os.pardir))
SLAVE_DIR = os.path.join(ROOT_PATH, 'slave', 'fake_slave', 'build')
BASE_DIRS = {
    'Public': os.path.dirname(SCRIPT_PATH)
}
# TODO(iannucci): Check for duplicate recipe names when we have more than one
# base_dir

COVERAGE = coverage.coverage(
    include=[os.path.join(x, 'recipes', '*') for x in BASE_DIRS.values()])


@contextlib.contextmanager
def cover():
  COVERAGE.start()
  try:
    yield
  finally:
    COVERAGE.stop()


class TestAPI(object):

  @staticmethod
  def tryserver_build_properties(**kwargs):
    ret = {
        'issue': 12853011,
        'patchset': 1,
        'blamelist': ['cool_dev1337@chromium.org'],
        'rietveld': 'https://chromiumcodereview.appspot.com',
    }
    ret.update(kwargs)
    return ret


def test_path_for_recipe(recipe_path):
  root = os.path.dirname(os.path.dirname(recipe_path))
  return os.path.join(root, 'recipes_test', os.path.basename(recipe_path))


def has_test(recipe_path):
  return os.path.exists(test_path_for_recipe(recipe_path))


def expected_for(recipe_path, test_name):
  test_base = os.path.splitext(test_path_for_recipe(recipe_path))[0]
  return '%s.%s.expected' % (test_base, test_name)


def exec_test_file(recipe_path):
  test_path = test_path_for_recipe(recipe_path)
  gvars = {}
  execfile(test_path, gvars)
  ret = {}
  for name, value in gvars.iteritems():
    if name.endswith('_test'):
      ret[name[:-len('_test')]] = value
  return ret


def execute_test_case(test_fn, recipe_path):
  test_data = test_fn(TestAPI())
  bp = test_data.get('build_properties', {})
  fp = test_data.get('factory_properties', {})
  fp['recipe'] = os.path.basename(os.path.splitext(recipe_path)[0])

  stream = annotator.StructuredAnnotationStream(stream=open(os.devnull, 'w'))
  with cover():
    with recipe_util.mock_paths():
      retval = annotated_run.make_steps(stream, bp, fp, True)
      assert retval.status_code is None
      return retval.script or retval.steps


def train_from_tests(recipe_path):
  if not has_test(recipe_path):
    print 'FATAL: Recipe %s has NO tests!' % recipe_path
    return False

  for path in glob(expected_for(recipe_path, '*')):
    os.unlink(path)

  for name, test_fn in exec_test_file(recipe_path).iteritems():
    steps = execute_test_case(test_fn, recipe_path)
    expected_path = expected_for(recipe_path, name)
    print 'Writing', expected_path
    with open(expected_path, 'w') as f:
      json.dump(steps, f, indent=2, sort_keys=True)

  return True


def load_tests(loader, _standard_tests, _pattern):
  """This method is invoked by unittest.main's automatic testloader."""
  def create_test_class(recipe_path):
    class RecipeTest(unittest.TestCase):
      def testExists(self):
        self.assertTrue(has_test(recipe_path))

      @classmethod
      def add_test_methods(cls):
        for name, test_fn in exec_test_file(recipe_path).iteritems():
          expected_path = expected_for(recipe_path, name)
          def test_(self):
            steps = execute_test_case(test_fn, recipe_path)
            # Roundtrip json to get same string encoding as load
            steps = json.loads(json.dumps(steps))
            with open(expected_path, 'r') as f:
              expected = json.load(f)
            self.assertEqual(steps, expected)
          test_.__name__ += name
          setattr(cls, test_.__name__, test_)

    if has_test(recipe_path):
      RecipeTest.add_test_methods()

    RecipeTest.__name__ += 'for_%s' % os.path.basename(recipe_path)
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
