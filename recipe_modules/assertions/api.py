# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import functools
import inspect
import sys
import unittest

from recipe_engine import recipe_api


# Change the value of the message for when a diff is omitted to refer to
# assertions.maxDiff instead of self.maxDiff.
unittest.case.DIFF_OMITTED = unittest.case.DIFF_OMITTED.replace(
    'self.maxDiff', 'assertions.maxDiff')

def make_assertion(assertion_method, **test_case_attrs):
  def assertion_wrapper(*args, **kwargs):
    class Asserter(unittest.TestCase):
      # The __init__ method of TestCase requires the name of a method on the
      # class that is the test to run. We're not going to run a test, we just
      # want access to the assertion methods, so just put some method.
      def __init__(self):
        super(Asserter, self).__init__('__init__')

      def _formatMessage(self, msg, standardMsg):
        if msg:
          # Extract the non-msg, non-self arguments to the assertion method to
          # be used in formatting custom messages e.g.
          # assertEqual(0, 1, '{first} should be {second}'), format_args will be
          # {'first': 0, 'second': 1} because the name of assertEqual's
          # arguments are named first and second
          call_args = inspect.getcallargs(assertion, *args, **kwargs)
          format_args = {k: v for k, v in call_args.iteritems()
                         if k not in ('self', 'msg')}
          msg = msg.format(**format_args)
        return super(Asserter, self)._formatMessage(msg, standardMsg)

    asserter = Asserter()
    for a, v in test_case_attrs.iteritems():
      setattr(asserter, a, v)
    assertion = getattr(asserter, assertion_method)

    try:
      assertion(*args, **kwargs)
    # Catch and throw a new exception so that the frames for unittest's
    # implementation aren't part of the displayed traceback
    except AssertionError as e:
      raise AssertionError(e.message)

  return assertion_wrapper


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

  The attributes longMessage and maxDiff are supported and have the same
  behavior as the unittest module.

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
    # The __init__ method of TestCase requires the name of a method on the class
    # that is the test to run. We're not going to run a test, we just want the
    # object to be able to read default values of attrs, so just put some
    # method.
    prototype = unittest.TestCase('__init__')
    self.longMessage = prototype.longMessage
    self.maxDiff = prototype.maxDiff

  def __getattr__(self, attr):
    if attr in self._TEST_CASE_WHITELIST:
      return make_assertion(
          attr, longMessage=self.longMessage, maxDiff=self.maxDiff)
    raise AttributeError("'%s' object has no attribute '%s'"
                         % (type(self).__name__, attr))
