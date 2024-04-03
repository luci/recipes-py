# -*- coding: utf-8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Internal helpers for reporting test status to stdout."""

import collections
import datetime
import logging
import os
import sys

from collections import defaultdict
from io import StringIO
from itertools import groupby

import attr
import coverage

from .fail_tracker import FailTracker
from ...warn.cause import CallSite, ImportSite


@attr.s
class Reporter:
  _recipe_deps = attr.ib()

  _use_emoji = attr.ib()
  _is_train = attr.ib()
  _fail_tracker = attr.ib()
  # If set, will print warning details (even if there are other fatal failures)
  _enable_warning_details = attr.ib()

  _column_count = attr.ib(default=0)
  _error_buf = attr.ib(factory=StringIO)

  _start_time = attr.ib(factory=datetime.datetime.now)

  # default to 80 cols if we're outputting to not a tty. Otherwise, set this to
  # -1 to allow the terminal to do all wrapping.
  #
  # This allows nice presentation on the bots (i.e. 80 columns), while also
  # allowing full-width display with correct wrapping on terminals/cmd.exe.
  _column_max = attr.ib()
  @_column_max.default
  def _column_max_default(self):
    # 1 == stdout
    return -1 if os.isatty(1) else 80

  _verbose = attr.ib()
  @_verbose.default
  def _verbose_default(self):
    return logging.getLogger().level < logging.WARNING

  def _space_for_columns(self, item_columns):
    """Preemptively ensures we have space to print something which takes
    `item_columns` space.

    Increments self._column_count as a side effect.
    """
    if self._column_max == -1:
      # output is a tty, let it do the wrapping.
      return

    self._column_count += item_columns
    if self._column_count > self._column_max:
      self._column_count = 0
      print()

  def short_report(self, outcome_msg, can_abort=True):
    """Prints all test results from `outcome_msg` to stdout.

    Detailed error messages (if any) will be accumulated in this reporter.

    NOTE: Will report and then raise SystemExit if the outcome_msg contains an
    'internal_error', as this indicates that the test harness is in an invalid
    state.

    Args:

      * outcome_msg (Outcome proto) - The message to report.
      * can_abort(bool) - True by default. Check whether the program should
        abort for a global failure found in test results.

    Returns:
      * bool - If test results have any failure.

    Raises SystemExit if outcome_msg has an internal_error.
    """
    # Global error; this means something in the actual test execution code went
    # wrong.
    if outcome_msg.internal_error:
      if can_abort:
        # This is pretty bad.
        print('ABORT ABORT ABORT')
        print('Global failure(s):')
        for failure in outcome_msg.internal_error:
          print('  ', failure)
      if can_abort:
        sys.exit(1)
      return True

    has_fail = False
    for test_name, test_result in outcome_msg.test_results.items():
      _print_summary_info(
          self._recipe_deps, self._verbose, self._use_emoji, test_name,
          test_result, self._space_for_columns)

      _print_detail_info(self._error_buf, test_name, test_result)

      has_fail = self._fail_tracker.cache_recent_fails(test_name,
                                                       test_result) or has_fail

    return has_fail


  def final_report(self, cov, outcome_msg):
    """Prints all final information about the test run to stdout.
    Raises SystemExit if the tests have failed.

    Args:

      * cov (coverage.Coverage|None) - The accumulated coverage data to report.
        If None, then no coverage analysis/report will be done. Coverage less
        than 100% counts as a test failure.
      * outcome_msg (Outcome proto) -
        Consulted for uncovered_modules and unused_expectation_files.
        coverage_percent is also populated as a side effect.
        Any uncovered_modules/unused_expectation_files count as a test failure.

    Side-effects: Populates outcome_msg.coverage_percent.

    Raises SystemExit if the tests failed.
    """
    self._fail_tracker.cleanup()

    fail = False
    if self._error_buf.tell() > 0:
      fail = True
      sys.stdout.write(
        'Errors in %s\n' % (self._error_buf.getvalue()))

    # For some integration tests we have repos which don't actually have any
    # recipe files at all. We skip coverage measurement if cov has no data.
    if cov and cov.get_data().measured_files():
      covf = StringIO()
      pct = 0
      try:
        pct = cov.report(file=covf, show_missing=True, skip_covered=True)
        outcome_msg.coverage_percent = pct
      except coverage.CoverageException as ex:
        print('%s: %s' % (ex.__class__.__name__, ex))
      if int(pct) != 100:
        fail = True
        print(covf.getvalue())
        print('FATAL: Insufficient total coverage (%.2f%%)' % pct)
        print()

    duration = (datetime.datetime.now() - self._start_time).total_seconds()
    print('-' * 70)
    print('Ran %d tests in %0.3fs' % (len(outcome_msg.test_results),
                                      duration))
    print()

    if outcome_msg.uncovered_modules:
      fail = True
      print('------')
      print('ERROR: The following modules lack any form of test coverage:')
      for modname in outcome_msg.uncovered_modules:
        print('  ', modname)
      print()
      print('Please add test recipes for them (e.g. recipes in the module\'s')
      print('"tests" subdirectory).')
      print()

    if outcome_msg.unused_expectation_files:
      fail = True
      print('------')
      print('ERROR: The below expectation files have no associated test case:')
      for expect_file in outcome_msg.unused_expectation_files:
        print('  ', expect_file)
      print()

    warning_result = _collect_warning_result(outcome_msg)
    if warning_result:
      print('------')
      if len(warning_result) == 1:
        print('Found 1 warning')
      else:
        print('Found %d warnings' % len(warning_result))
      print()
      if self._enable_warning_details or not fail:
        _print_warnings(warning_result, self._recipe_deps)
      else:
        print('Fix test failures or pass --show-warnings for details.')
      print()

    status_warning_result = _collect_global_warnings_result(outcome_msg)
    if status_warning_result:
      print('------')
      print('Found these warnings in the following tests:')
      for test_name, warning in sorted(status_warning_result):
        print('\t%s - %s' % (test_name, warning))
      print()

    if fail:
      print('------')
      print('FAILED')
      print()
      if not self._is_train:
        print('NOTE: You may need to re-train the expectation files by running')
        print()
        print('  ./recipes.py test train')
        print()
        print('This will update all the .json files to have content which')
        print('matches the current recipe logic. Review them for correctness')
        print('and include them with your CL.')
      sys.exit(1)

    print('------')
    print('TESTS OK')


# Internal helper stuff

# Map of top-level field name (in recipe_engine.internal.test.Outcome)
# to:
#
#   (success, verbose message, emoji icon, text icon)
#
# _check_field will scan for the first entry which has fields set.
FIELD_TO_DISPLAY = collections.OrderedDict([
  ('internal_error', (False, 'internal testrunner error',           '🆘', '!')),

  ('bad_test',       (False, 'test specification was bad/invalid',  '🛑', 'S')),
  ('crash_mismatch', (False, 'recipe crashed in an unexpected way', '🔥', 'E')),
  ('check',          (False, 'failed post_process check(s)',        '❌', 'X')),
  ('diff',           (False, 'expectation file has diff',           '⚡', 'D')),

  ('removed',        (True,  'removed expectation file',            '🌟', 'R')),
  ('written',        (True,  'updated expectation file',            '💾', 'D')),

  ('global_warnings', (True, 'warning emitted',                     '❗', 'W')),
])


def _check_field(test_result, field_name):
  for descriptor, value in test_result.ListFields():
    if descriptor.name == field_name:
      return FIELD_TO_DISPLAY[field_name], value

  return (None, None, None, None), None


def _print_summary_info(recipe_deps, verbose, use_emoji, test_name, test_result,
                        space_for_columns):
  # Pick the first populated field in the TestResults.Results
  for field_name in FIELD_TO_DISPLAY:
    (success, verbose_msg, emj, txt), _ = _check_field(test_result, field_name)
    icon = emj if use_emoji else txt
    if icon:
      break

  # handle warnings and 'nothing' specially:
  if not icon:
    success = True
    for warning_name in test_result.warnings:
      if recipe_deps.warning_definitions[warning_name].deadline:
        icon = '🟡' if use_emoji else 'W'
        verbose_msg = 'warnings with deadline'
        break
    else:
      verbose_msg = 'warnings'

  if not icon:
    icon = '.'

  if verbose:
    msg = '' if not verbose_msg else ' (%s)' % verbose_msg
    print('%s ... %s%s' % (test_name, 'ok' if success else 'FAIL', msg))
  else:
    space_for_columns(1 if len(icon) == 1 else 2)
    sys.stdout.write(icon)
  sys.stdout.flush()


def _print_detail_info(err_buf, test_name, test_result):
  verbose_msg = None

  def _header():
    print('=' * 70, file=err_buf)
    print('FAIL (%s) - %s' % (verbose_msg, test_name), file=err_buf)
    print('-' * 70, file=err_buf)

  for field in ('internal_error', 'bad_test', 'crash_mismatch'):
    (_, verbose_msg, _, _), lines = _check_field(test_result, field)
    if lines:
      _header()
      for line in lines:
        print(line, file=err_buf)
      print(file=err_buf)

  (_, verbose_msg, _, _), lines_groups = _check_field(test_result, 'check')
  if lines_groups:
    _header()
    for group in lines_groups:
      for line in group.lines:
        print(line, file=err_buf)
      print(file=err_buf)

  (_, verbose_msg, _, _), lines = _check_field(test_result, 'diff')
  if lines:
    _header()
    for line in lines.lines:
      print(line, file=err_buf)
    print(file=err_buf)


@attr.s
class PerWarningResult:
  call_sites = attr.ib(factory=set)
  import_sites = attr.ib(factory=set)


def _collect_warning_result(outcome_msg):
  """Collects issued warnings from all test outcomes and dedupes causes for
  each warning.
  """
  result = defaultdict(PerWarningResult)
  for _, test_result in outcome_msg.test_results.items():
    for name, causes in test_result.warnings.items():
      for cause in causes.causes:
        if cause.WhichOneof('oneof_cause') == 'call_site':
          result[name].call_sites.add(CallSite.from_cause_pb(cause))
        else:
          result[name].import_sites.add(ImportSite.from_cause_pb(cause))
  return result


def _collect_global_warnings_result(outcome_msg):
  result = []
  for test_name, test_result in outcome_msg.test_results.items():
    _, warnings = _check_field(test_result, 'global_warnings')
    if warnings:
      for warning in warnings:
        result.append((test_name, warning))
  return result


def _print_warnings(warning_result, recipe_deps):
  def print_bug_links(definition):
    bug_links = [
      f'https://{bug.host}/p/{bug.project}/issues/detail?id={bug.id}'
      for bug in definition.monorail_bug
    ] + [
      f'https://{iss.host}/{iss.id}'
      for iss in definition.google_issue
    ]

    if bug_links:
      print()
      if len(bug_links) == 1:
        print(f'Bug Link: {bug_links[0]}')
      else:
        print('Bug Links:')
        for link in bug_links:
          print(f'  {link}')


  def print_call_sites(call_sites):
    def stringify_frame(frame):
      return ':'.join((os.path.normpath(frame.file), str(frame.line)))

    if not call_sites:
      return
    print('Call Sites:')
    sorted_sites = sorted(call_sites,
                          key=lambda s: (s.site.file, s.site.line))
    if sorted_sites[0].call_stack:
      # call site contains the full stack.
      for call_site in sorted_sites:
        print('  site: %s' % stringify_frame(call_site.site))
        print('  stack:')
        for f in call_site.call_stack:
          print('    ' +stringify_frame(f))
        print()
    else:
      for file_name, sites in groupby(sorted_sites, key=lambda s: s.site.file):
        # Print sites that have the same file in a single line.
        # E.g. /path/to/site:123 (and 456, 789)
        site_iter = iter(sites)
        line = stringify_frame(next(site_iter).site)
        additional_lines = ', '.join(str(s.site.line) for s in site_iter)
        if additional_lines:
          line =  '%s (and %s)' % (line, additional_lines)
        print('  ' + line)

  def print_import_sites(import_sites):
    if not import_sites:
      return
    print('Import Sites:')
    for import_site in sorted(import_sites,
                              key=lambda s: (
                                s.repo or "", s.module or "", s.recipe or "")):
      repo = recipe_deps.repos[import_site.repo]
      if import_site.module:
        mod_path = repo.modules[import_site.module].path
        print('  %s' % os.path.normpath(os.path.join(mod_path, '__init__.py')))
      else:
        print('  %s' % os.path.normpath(repo.recipes[import_site.recipe].path))

  for warning_name in sorted(warning_result):
    causes = warning_result[warning_name]
    print('*' * 70)
    print('{:^70}'.format('WARNING: %s' % warning_name))
    print('{:^70}'.format('Found %d call sites and %d import sites' % (
        len(causes.call_sites), len(causes.import_sites),)))
    print('*' * 70)
    definition = recipe_deps.warning_definitions[warning_name]
    if definition.description:
      print('Description:')
      for desc in definition.description:
        print('  %s' % desc)
    if definition.deadline:
      print('Deadline: %s' % definition.deadline)
    print_bug_links(definition)
    print_call_sites(causes.call_sites)
    print_import_sites(causes.import_sites)
