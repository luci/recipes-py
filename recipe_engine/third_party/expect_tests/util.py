# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import inspect

EXPECT_TESTS_COVER_FUNCTION = 'EXPECT_TESTS_COVER_FUNCTION'

def covers(coverage_path_function):
  """Allows annotation of a Test generator function with a function that will
  return a list of coverage patterns which should be enabled during the use of
  the Test generator function.
  """
  def _decorator(func):
    setattr(func, EXPECT_TESTS_COVER_FUNCTION, coverage_path_function)
    return func
  return _decorator


def get_cover_list(test_gen_function):
  """Given a Test generator, return the list of coverage globs that should
  be included while executing the Test generator."""
  return getattr(test_gen_function, EXPECT_TESTS_COVER_FUNCTION,
                 lambda: [inspect.getabsfile(test_gen_function)])()
