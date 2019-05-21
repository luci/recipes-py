# -*- coding: utf-8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Internal helpers for reporting test status to stdout."""


import collections
import datetime
import logging
import sys

from cStringIO import StringIO

import coverage


def test_cases_to_stdout(outcome_msg, err_buf):
  """Prints all test results from `outcome_msg` to stdout.

  Detailed error messages (if any) will be written to err_buf.

  NOTE: Will report and then raise SystemExit if the outcome_msg contains an
  'internal_error', as this indicates that the test harness is in an invalid
  state.

  Args:

    * outcome_msg (Outcome proto) - The message to report.
    * err_buf (file-like object) - The buffer (usually StringIO) to render error
      messages to.

  Raises SystemExit if outcome_msg has an internal_error.
  """
  # Global error; this means something in the actual test execution code went
  # wrong.
  if outcome_msg.internal_error:
    # This is pretty bad.
    print 'ABORT ABORT ABORT'
    print 'Global failure(s):'
    for failure in outcome_msg.internal_error:
      print '  ', failure
    sys.exit(1)

  for test_name, test_result in outcome_msg.test_results.iteritems():
    _print_summary_info(test_name, test_result)
    _print_detail_info(err_buf, test_name, test_result)


def final_summary_to_stdout(err_buf, is_train, cov, outcome_msg, start_time):
  """Prints all final information about the test run to stdout. Raises
  SystemExit if the tests have failed.

  Args:

    * err_buf (file-like object) - This should be populated with all buffered
      error reports (i.e. from `test_cases_to_stdout()`). If this buffer
      contains anything, it counts as a test failure.
    * is_train (bool) - True iff we're in train mode. If False and the test
      failed, prints instructions on how to re-train the expectations.
    * cov (coverage.Coverage|None) - The accumulated coverage data to report.
      If None, then no coverage analysis/report will be done. Coverage less than
      100% counts as a test failure.
    * outcome_msg (Outcome proto) - Consulted for uncovered_modules and
      unused_expectation_files. coverage_percent is also populated as a side
      effect. Any uncovered_modules/unused_expectation_files count as test
      failure.
    * start_time (datetime.datetime) - The time that we started running the
      tests.

  Side-effects: Populates outcome_msg.coverage_percent.

  Raises SystemExit if the tests failed.
  """
  fail = err_buf.tell() > 0

  print
  sys.stdout.write(err_buf.getvalue())

  if cov:
    covf = StringIO()
    try:
      outcome_msg.coverage_percent = cov.report(
          file=covf, show_missing=True, skip_covered=True)
    except coverage.CoverageException as ex:
      print '%s: %s' % (ex.__class__.__name__, ex)
    if int(outcome_msg.coverage_percent) != 100:
      fail = True
      print covf.getvalue()
      print 'FATAL: Insufficient coverage (%.2f%%)' % (
        outcome_msg.coverage_percent,)
      print

  duration = (datetime.datetime.now() - start_time).total_seconds()
  print '-' * 70
  print 'Ran %d tests in %0.3fs' % (len(outcome_msg.test_results), duration)
  print

  if outcome_msg.uncovered_modules:
    fail = True
    print '------'
    print 'ERROR: The following modules lack any form of test coverage:'
    for modname in outcome_msg.uncovered_modules:
      print '  ', modname
    print
    print 'Please add test recipes for them (e.g. recipes in the module\'s'
    print '"tests" subdirectory).'
    print

  if outcome_msg.unused_expectation_files:
    fail = True
    print '------'
    print 'ERROR: The following expectation files have no associated test case:'
    for expect_file in outcome_msg.unused_expectation_files:
      print '  ', expect_file
    print

  if fail:
    print '------'
    print 'FAILED'
    print
    if not is_train:
      print 'NOTE: You may need to re-train the expectation files by running:'
      print
      print '  ./recipes.py test train'
      print
      print 'This will update all the .json files to have content which matches'
      print 'the current recipe logic. Review them for correctness and include'
      print 'them with your CL.'
    sys.exit(1)

  print 'OK'


# Internal helper stuff


FIELD_TO_DISPLAY = collections.OrderedDict([
  # pylint: disable=bad-whitespace
  ('internal_error', (False, 'internal testrunner error',           '🆘')),

  ('bad_test',       (False, 'test specification was bad/invalid',  '🛑')),
  ('crash_mismatch', (False, 'recipe crashed in an unexpected way', '🔥')),
  ('check',          (False, 'failed post_process check(s)',        '❌')),
  ('diff',           (False, 'expectation file has diff',           '⚡')),

  ('removed',        (True,  'removed expectation file',            '🌟')),
  ('written',        (True,  'updated expectation file',            '📜')),

  (None,             (True,  '',                                    '✅'))
])


def _check_field(test_result, field_name):
  if field_name is None:
    return FIELD_TO_DISPLAY[field_name], None

  for descriptor, value in test_result.ListFields():
    if descriptor.name == field_name:
      return FIELD_TO_DISPLAY[field_name], value

  return (None, None, None), None


_VERBOSE = logging.getLogger().level < logging.WARNING


def _print_summary_info(test_name, test_result):
  # Pick the first populated field in the TestResults.Results
  for field_name in FIELD_TO_DISPLAY:
    (success, verbose_msg, icon), _ = _check_field(test_result, field_name)
    if icon:
      break

  if _VERBOSE:
    msg = '' if not verbose_msg else ' (%s)' % verbose_msg
    print '%s ... %s%s' % (test_name, 'ok' if success else 'FAIL', msg)
  else:
    sys.stdout.write(icon)
  sys.stdout.flush()


def _print_detail_info(err_buf, test_name, test_result):
  verbose_msg = None

  def _header():
    print >>err_buf, '=' * 70
    print >>err_buf, 'FAIL (%s) - %s' % (verbose_msg, test_name)
    print >>err_buf, '-' * 70

  for field in ('internal_error', 'bad_test', 'crash_mismatch'):
    (_, verbose_msg, _), lines = _check_field(test_result, field)
    if lines:
      _header()
      for line in lines:
        print >>err_buf, line
      print >>err_buf

  (_, verbose_msg, _), lines_groups = _check_field(test_result, 'check')
  if lines_groups:
    for idx, group in enumerate(lines_groups):
      _header()
      if idx != 0:
        print >>err_buf, '  ------'
      for line in group.lines:
        print >>err_buf, line
      print >>err_buf

  (_, verbose_msg, _), lines = _check_field(test_result, 'diff')
  if lines:
    _header()
    for line in lines.lines:
      print >>err_buf, line
    print >>err_buf
