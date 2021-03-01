# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import attr

class ClosedFailFile:
  """Sentinel class that replaced the fail file after it's been closed."""
  pass

class FailFileAlreadyClosedException(Exception):
  """An exception that is raised when FailTracker.cleanup() is called twice."""
  pass

@attr.s
class FailTracker(object):
  """Tracks which tests have failed since the last run.

  Saves the failures to a file, and loads them into an instance variable to run
  first in subsequent runs. The file gets cleared only once results start
  flowing in, so if a run is canceled early, the fail cache will remain
  unharmed.
  """
  _fail_file_path = attr.ib()

  _fail_file = attr.ib(default=None, type=file)
  _recent_fails = attr.ib(factory=set)

  def __attrs_post_init__(self):
    try:
      with open(self._fail_file_path) as f:
        self._recent_fails = set(f.read().splitlines())
    except IOError:
      self._recent_fails = set()

  @property
  def recent_fails(self):
    """Contains the contents of the .previous_fails file, which is a newline
    separated list of recipe.test_case that failed last run."""
    return self._recent_fails

  def cache_recent_fails(self, test_name, test_result):
    """Caches recently failed test cases to a file

    Args:

      * test_name: Name of the test that just ran (str)
      * test_result: The result of that test (Outcome.Results)

    Returns whether the test failed. (bool)
    """
    if FailTracker.test_failed(test_result):
      if self._fail_file is None:
        # This file is left open because we write to it in repeated
        # calls to this function. We also don't want to open it prior to this
        # time because we don't want to truncate the file before results start
        # flowing in.
        # self._fail_file is closed by Reporter.final_report() calling
        # FailTracker.cleanup(). If the program terminates unexpectedly and it
        # isn't closed, it shouldn't be the end of the world.
        self._fail_file = open(self._fail_file_path, 'w')

      self._fail_file.write('%s\n' % test_name)
      self._fail_file.flush()
      return True
    return False

  def cleanup(self):
    """Cleans up the dangling file pointer that this class uses.

    This should be called once all test results have been streamed to the
    FailTracker
    """

    # The file is left open once results start streaming in, thus the 'if'
    if isinstance(self._fail_file, ClosedFailFile):
      raise FailFileAlreadyClosedException()
    elif self._fail_file is not None:
      self._fail_file.close()
      self._fail_file = ClosedFailFile()

  @staticmethod
  def test_failed(test_result):
    """Returns whether a test failed."""
    error_fields = set(('internal_error', 'bad_test', 'crash_mismatch', 'check',
                        'diff'))
    result_fields = set(
        descriptor.name for descriptor, value in test_result.ListFields())
    return error_fields & result_fields
