# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from .type_definitions import Test, Result, MultiTest, FuncCall, Bind


def _SetUpClass(test_class):
  inst = test_class('__init__')
  inst.setUpClass()
  return inst


def _TearDownClass(test_class_inst):
  test_class_inst.tearDownClass()


def _RunTestCaseSingle(test_case, test_name, test_instance=None):
  # The hack is so that unittest.TestCase has something to pretend is the
  # test method without the BS of wrapping each method in a new TestCase
  # class...
  test_instance = test_instance or test_case('__init__')
  test_instance.setUp()
  try:
    return Result(getattr(test_instance, test_name)())
  finally:
    test_instance.tearDown()


def UnittestTestCase(test_case, name_prefix='', ext='json'):
  """Yield a MultiTest or multiple Test instances for the unittest.TestCase
  derived |test_case|.

  If the TestCase has a field `__expect_tests_serial__` defined to be True, then
  all test methods in the TestCase will be guaranteed to run in a single process
  with the same instance. This is automatically set to True if your test class
  relies on setUpClass/tearDownClass.

  If the TestCase has a field `__expect_tests_atomic__` defined to be True, then
  in the event of a test filter which matches any test method in |test_case|,
  the ENTIRE |test_case| will be executed (i.e. the TestCase has interdependant
  test methods). This should only need to be set for very poorly designed tests.

  `__expect_tests_atomic__` implies `__expect_tests_serial__`.

  @type test_case: unittest.TestCase
  """
  name_prefix = name_prefix + test_case.__name__
  def _tests_from_class(cls, *args, **kwargs):
    for test_name in unittest.defaultTestLoader.getTestCaseNames(cls):
      yield Test(
          name_prefix + '.' + test_name,
          FuncCall(_RunTestCaseSingle, cls, test_name, *args, **kwargs),
          ext=ext, break_funcs=[getattr(cls, test_name)],
      )

  if hasattr(test_case, '__expect_tests_serial__'):
    serial = getattr(test_case, '__expect_tests_serial__', False)
  else:
    default_setup = unittest.TestCase.setUpClass.im_func
    default_teardown = unittest.TestCase.tearDownClass.im_func
    serial = (
        test_case.setUpClass.im_func is not default_setup or
        test_case.tearDownClass.im_func is not default_teardown)

  atomic = getattr(test_case, '__expect_tests_atomic__', False)
  if atomic or serial:
    yield MultiTest(
        name_prefix,
        FuncCall(_SetUpClass, test_case),
        FuncCall(_TearDownClass, Bind(name='context')),
        list(_tests_from_class(test_case, test_instance=Bind(name='context'))),
        atomic
    )
  else:
    for test in _tests_from_class(test_case):
      yield test


def UnitTestModule(test_module, name_prefix='', ext='json'):
  """Yield MultiTest's and/or Test's for the python module |test_module| which
  contains zero or more unittest.TestCase implementations.

  @type test_module: types.ModuleType
  """
  name_prefix = name_prefix + test_module.__name__ + '.'
  for name in dir(test_module):
    obj = getattr(test_module, name)
    if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
      for test in UnittestTestCase(obj, name_prefix, ext):
        yield test
    # TODO(iannucci): Make this compatible with the awful load_tests hack?
