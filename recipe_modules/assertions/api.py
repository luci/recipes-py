# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import functools
import inspect
import sys
import unittest

from recipe_engine import recipe_api

TracebackProxy = collections.namedtuple(
    'TracebackProxy', ['tb_frame', 'tb_lasti', 'tb_lineno', 'tb_next'])

def assertion_wrapper(assertion, *args, **kwargs):
  class Asserter(unittest.TestCase):
    def __init__(self):
      super(Asserter, self).__init__('dummy_method')

    def dummy_method(self):
      """Does nothing.

      The __init__ method for unittest.TestCase requires the name of a method on
      the class that is the test being run, so a "test" method must be provided.
      """
      pass  # pragma: no cover

    def _formatMessage(self, msg, standardMsg):
      if msg:
        # Extract the non-msg, non-self arguments to the assertion method to be
        # used in formatting custom messages
        # e.g. assertEqual(0, 1, '{first} should be {second}'), format_args will
        # be {'first': 0, 'second': 1} because the name of assertEqual's
        # arguments are named first and second
        call_args = inspect.getcallargs(
            getattr(self, assertion), *args, **kwargs)
        format_args = {k: v for k, v in call_args.iteritems()
                       if k not in ('self', 'msg')}
        msg = msg.format(**format_args)
      return super(Asserter, self)._formatMessage(msg, standardMsg)

  try:
    getattr(Asserter(), assertion)(*args, **kwargs)

  # Catch and throw a new exception so that the frames for unittest's
  # implementation aren't part of the displayed traceback
  except AssertionError as e:
    raise AssertionError(e.message)


class AssertionsApi(recipe_api.RecipeApi):
  """Provides access to the assertion methods of the python unittest module.

  Asserting non-step aspects of code (return values, non-step side effects) is
  expressed more naturally by making assertions within the RunSteps function of
  the test recipe. This api provides access to the assertion methods of
  unittest.TestCase to be used within test recipes.

  The methods of unittest.TestCase can be used with the following exceptions:
  * assertLogs
  * all methods deprecated in favor of a newer method

  An enhancement to the assertion methods is that if a custom msg is used,
  values for the non-msg arguments can be substituted into the message using
  named substitution with the format method of strings.
  e.g. self.AssertEqual(0, 1, '{first} should be {second}') will raise an
  AssertionError with the message: '0 should be 1'.

  Example (.../recipe_modules/my_module/tests/foo.py):
  DEPS = [
      'my_module',
      'recipe_engine/assertions',
      'recipe_engine/properties',
      'recipe_engine/runtime',
  ]

  def RunSteps(api):
    # Behavior of foo depends on whether build is experimental
    value = api.my_module.foo()
    expected_value = api.properties.get('expected_value')
    api.assertions.assertEqual(value, expected_value)

  def GenTests(api):
    yield (
        api.test('basic')
        + api.properties(expected_value='normal value')
    )

    yield (
        api.test('experimental')
        + api.properties(expected_value='experimental value')
        + api.properties(is_luci=True, is_experimental=True)
   )
  """

  # Not included: assertLogs, all of the deprecated assertion methods, all
  # non-methods
  _TEST_CASE_WHITELIST = [
      'assertAlmostEqual', 'assertCountEqual', 'assertDictContainsSubset',
      'assertDictEqual', 'assertEqual', 'assertFalse', 'assertGreater',
      'assertGreaterEqual', 'assertIn', 'assertIs', 'assertIsInstance',
      'assertIsNone', 'assertIsNot', 'assertIsNotNone', 'assertLess',
      'assertLessEqual', 'assertListEqual', 'assertMultiLineEqual',
      'assertNotAlmostEqual', 'assertNotEqual', 'assertNotIn',
      'assertNotIsInstance', 'assertNotRegex', 'assertRaises',
      'assertRaisesRegex', 'assertRegex', 'assertSequenceEqual',
      'assertSetEqual', 'assertTrue', 'assertTupleEqual', 'assertWarns',
      'assertWarnsRegex', 'fail',
  ]

  def __init__(self, *args, **kwargs):
    super(AssertionsApi, self).__init__(*args, **kwargs)
    if not self._test_data.enabled:  # pragma: no cover
      raise Exception('assertions module is only for use in tests')

  def __getattr__(self, attr):
    if attr in self._TEST_CASE_WHITELIST:
      return functools.partial(assertion_wrapper, attr)
    raise AttributeError("'%s' object has no attribute '%s'"
                         % (type(self).__name__, attr))
