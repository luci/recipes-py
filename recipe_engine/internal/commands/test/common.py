# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os

# pylint: disable=import-error
from PB.recipe_engine.test_result import TestResult

from ...test.test_util import filesystem_safe


class TestFailure(object):
  """Base class for different kinds of test failures."""

  def format(self):
    """Returns a human-readable description of the failure."""
    raise NotImplementedError()

  def as_proto(self):
    """Returns a machine-readable description of the failure as proto.

    The returned message should be an instance of TestResult.TestFailure
    (see test_result.proto).
    """
    raise NotImplementedError()


class DiffFailure(TestFailure):
  """Failure when simulated recipe commands don't match recorded expectations.
  """

  def __init__(self, diff):
    self.diff = diff

  def format(self):
    return self.diff

  def as_proto(self):
    proto = TestResult.TestFailure()
    proto.diff_failure.MergeFrom(TestResult.DiffFailure())
    return proto


class CheckFailure(TestFailure):
  """Failure when any of the post-process checks fails."""

  def __init__(self, check):
    self.check = check

  def format(self):
    return self.check.format(indent=4)

  def as_proto(self):
    return self.check.as_proto()


class BadTestFailure(TestFailure):
  """Failure when the test itself was bad somehow (e.g. provides mock data
  for steps which never ran)."""

  def __init__(self, error):
    self.error = error

  def format(self):
    return str(self.error)

  def as_proto(self):
    proto = TestResult.TestFailure()
    proto.bad_test_failure.error = self.error
    return proto


class CrashFailure(TestFailure):
  """Failure when the recipe run crashes with an uncaught exception."""

  def __init__(self, error):
    self.error = error

  def format(self):
    return str(self.error)

  def as_proto(self):
    proto = TestResult.TestFailure()
    proto.crash_failure.error = self.error
    return proto


class TestResult_(object):
  """Result of running a test."""

  def __init__(self, test_description, failures, coverage_data,
               generates_expectation):
    self.test_description = test_description
    self.failures = failures
    self.coverage_data = coverage_data
    self.generates_expectation = generates_expectation


class TestDescription(object):
  """Identifies a specific test.

  Deliberately small and picklable for use with multiprocessing."""

  def __init__(self, recipe_name, test_name, expect_dir, covers):
    self.recipe_name = recipe_name
    self.test_name = test_name
    self.expect_dir = expect_dir
    self.covers = covers

  @staticmethod
  def test_case_full_name(recipe_name, test_name):
    return '%s.%s' % (recipe_name, test_name)

  @property
  def full_name(self):
    return self.test_case_full_name(self.recipe_name, self.test_name)

  @property
  def expectation_path(self):
    name = filesystem_safe(self.test_name)
    return os.path.join(self.expect_dir, name + '.json')
