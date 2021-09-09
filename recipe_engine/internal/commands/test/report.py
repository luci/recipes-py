# -*- coding: utf-8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Internal helpers for reporting test status to stdout."""


from __future__ import print_function
from future.utils import iteritems


import collections
import datetime
import logging
import os
import sys

from collections import defaultdict
from itertools import groupby

import attr
import coverage

from .fail_tracker import FailTracker
from ...warn.cause import CallSite, ImportSite


_PY2 = sys.version_info.major == 2
if _PY2:
  from cStringIO import StringIO
else:
  from io import StringIO


@attr.s
class Reporter(object):
  _use_emoji = attr.ib()
  _is_train = attr.ib()
  _fail_tracker = attr.ib()
  # Whether to show details for py3 implicit tests.
  _enable_py3_details = attr.ib()

  _column_count = attr.ib(default=0)
  _long_err_buf = attr.ib(factory=dict)  # {'py2': StringIO, 'py3': StringIO}
  # store the err msg which may be caused not by the recipe itself, but the
  # discrepancy of supported python version between the recipe and its deps.
  # The dict structure is {'py2': StringIO, 'py3': StringIO}.
  _maybe_soft_failure_buf = attr.ib(factory=dict)

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

  def __attrs_post_init__(self):
    self._long_err_buf['py2'] = StringIO()
    self._long_err_buf['py3'] = StringIO()
    self._maybe_soft_failure_buf['py2'] = StringIO()
    self._maybe_soft_failure_buf['py3'] = StringIO()

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

  def short_report(self, outcome_msg, py='py2', can_abort=True):
    """Prints all test results from `outcome_msg` to stdout.

    Detailed error messages (if any) will be accumulated in this reporter.

    NOTE: Will report and then raise SystemExit if the outcome_msg contains an
    'internal_error', as this indicates that the test harness is in an invalid
    state.

    Args:

      * outcome_msg (Outcome proto) - The message to report.
      * py (String) - Indicate which python mode it uses. The value should be
        either py2 or py3.
      * can_abort(bool) - True by default. Check whether the program should
        abort for a global failure found in test results.

    Returns:
      * bool - If test results have any failure.
      * int - The error count. NOTE: if py='py3' but --py3-details flag is not
              set, then counts implicit py3 tests only. We only count error in
              that situation.

    Raises SystemExit if outcome_msg has an internal_error.
    """
    # Global error; this means something in the actual test execution code went
    # wrong.
    if outcome_msg.internal_error:
      if can_abort or (py == 'py3' and self._enable_py3_details):
        # This is pretty bad.
        print('ABORT ABORT ABORT')
        print('Global failure(s):')
        for failure in outcome_msg.internal_error:
          print('  ', failure)
      if (py == 'py3' and 'Broken pipe' in outcome_msg.internal_error[0] and
          not self._enable_py3_details):
        print('py3 runner may exit unexpectedly. '
              'Pass --py3-details to see more')
      if can_abort:
        sys.exit(1)
      return True, len(outcome_msg.test_results)

    err_count = 0
    has_fail = False
    for test_name, test_result in iteritems(outcome_msg.test_results):
      if (py == 'py3' and not self._enable_py3_details and
          not test_result.labeled_py_compat):
        err_count += 1 if FailTracker.test_failed(test_result) else 0
        continue

      _print_summary_info(
          self._verbose, self._use_emoji, test_name, test_result,
          self._space_for_columns)
      buf = (self._maybe_soft_failure_buf[py]
             if test_result.expect_py_incompatibility
             else self._long_err_buf[py])
      _print_detail_info(buf, test_name, test_result)

      has_fail = self._fail_tracker.cache_recent_fails(test_name,
                                                       test_result) or has_fail

    return has_fail, err_count


  def final_report(self, cov, outcome_msgs, recipe_deps):
    """Prints all final information about the py2 and py3 test run to stdout.
    Raises SystemExit if the tests have failed.

    Args:

      * cov (coverage.Coverage|None) - The accumulated coverage data to report.
        If None, then no coverage analysis/report will be done. Coverage less
        than 100% counts as a test failure.
      * outcome_msgs (TestResults(py2=Outcome proto, py3=Outcome proto)) -
        Consulted for uncovered_modules and unused_expectation_files.
        coverage_percent is also populated as a side effect.
        Any uncovered_modules/unused_expectation_files count as a test failure.
      * recipe_deps (RecipeDeps) - The loaded recipe repo dependencies.

    Side-effects: Populates outcome_msg.coverage_percent.

    Raises SystemExit if the tests failed.
    """
    self._fail_tracker.cleanup()

    print()
    soft_fail, fail = False, False
    for py in ('py2', 'py3'):
      soft_fail = soft_fail or self._maybe_soft_failure_buf[py].tell() > 0
      if self._long_err_buf[py].tell() > 0:
        fail = True
        sys.stdout.write(
          'Errors in %s %s\n' % (py, self._long_err_buf[py].getvalue()))

    # For some integration tests we have repos which don't actually have any
    # recipe files at all. We skip coverage measurement if cov has no data.
    if cov and cov.get_data().measured_files():
      covf = StringIO()
      pct = 0
      try:
        pct = cov.report(file=covf, show_missing=True, skip_covered=True)
        outcome_msgs.py2.coverage_percent = pct
        outcome_msgs.py3.coverage_percent = pct
      except coverage.CoverageException as ex:
        print('%s: %s' % (ex.__class__.__name__, ex))
      if int(pct) != 100:
        fail = True
        print(covf.getvalue())
        print('FATAL: Insufficient total coverage for py2+py3 (%.2f%%)' % pct)
        print()

    duration = (datetime.datetime.now() - self._start_time).total_seconds()
    print('-' * 70)
    print('Ran %d tests in %0.3fs' % (len(outcome_msgs.py2.test_results) +
                                      len(outcome_msgs.py3.test_results),
                                      duration))
    print()

    # We have a combined coverage report, hence the uncovered_modules is also
    # shared between py2 and py3. Only need to use one of them to print
    # uncovered_modules info.
    if outcome_msgs.py2.uncovered_modules:
      fail = True
      print('------')
      print('ERROR: The following modules lack any form of test coverage:')
      for modname in outcome_msgs.py2.uncovered_modules:
        print('  ', modname)
      print()
      print('Please add test recipes for them (e.g. recipes in the module\'s')
      print('"tests" subdirectory).')
      print()

    if outcome_msgs.py2.unused_expectation_files:
      fail = True
      print('------')
      print('ERROR: The below expectation files have no associated test case:')
      for expect_file in outcome_msgs.py2.unused_expectation_files:
        print('  ', expect_file)
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

    warning_result = _collect_warning_result(outcome_msgs)
    if warning_result:
      _print_warnings(warning_result, recipe_deps)
      print('------')
      print('TESTS OK with %d warnings' % len(warning_result))
    elif soft_fail:
      print('=======Possible Soft Failures Below=======')
      if self._maybe_soft_failure_buf['py2'].tell() > 0:
        print('Soft errors in py2 tests:')
        print(self._maybe_soft_failure_buf['py2'].getvalue())
      if self._maybe_soft_failure_buf['py3'].tell() > 0:
        print('Soft errors in py3 tests:')
        print(self._maybe_soft_failure_buf['py3'].getvalue())
      print('------')
      print('TESTS OK but have soft failures shown above. It indicates that')
      print('the claimed PYTHON_VERSION_COMPATIBILITY of the recipe disagrees')
      print('with that of its dependencies. However, recipe engine has no way')
      print('to tell whether tests fail because of this discrepancy or a real')
      print('bug inside the recipe. Therefore, tests are considered succeeded.')
      print()
      print('Please use your own judgement to determine the real cause.')
      print('You can use `recipes.py deps` command to check which dependency')
      print('has claimed an incompatible python version.')
      print()
      print('NOTE: any errors will become hard failures if they still persist')
      print('after all dependencies have claimed a compatible python version')
      print('(i.e. finished py3 migration). So, if you are unsure, please wait')
      print('for the Python 3 migration of your dependencies before marking ')
      print('your recipe as Python 3 compatible.')
    else:
      print('TESTS OK')



# Internal helper stuff


FIELD_TO_DISPLAY = collections.OrderedDict([
  # pylint: disable=bad-whitespace
  ('internal_error', (False, 'internal testrunner error',           '🆘', '!')),

  ('bad_test',       (False, 'test specification was bad/invalid',  '🛑', 'S')),
  ('crash_mismatch', (False, 'recipe crashed in an unexpected way', '🔥', 'E')),
  ('check',          (False, 'failed post_process check(s)',        '❌', 'X')),
  ('diff',           (False, 'expectation file has diff',           '⚡', 'D')),

  ('warnings',       (True,  'encounter warning(s)',                '🟡', 'W')),
  ('removed',        (True,  'removed expectation file',            '🌟', 'R')),
  ('written',        (True,  'updated expectation file',            '💾', 'D')),

  # We use '.' even in emoji mode as this is the vast majority of outcomes when
  # training recipes. This makes the other icons pop much better.
  (None,             (True,  '',                                    '.', '.'))
])


def _check_field(test_result, field_name):
  if field_name is None:
    return FIELD_TO_DISPLAY[field_name], None

  for descriptor, value in test_result.ListFields():
    if descriptor.name == field_name:
      return FIELD_TO_DISPLAY[field_name], value

  return (None, None, None, None), None


def _print_summary_info(verbose, use_emoji, test_name, test_result,
                        space_for_columns):
  # Pick the first populated field in the TestResults.Results
  for field_name in FIELD_TO_DISPLAY:
    (success, verbose_msg, emj, txt), _ = _check_field(test_result, field_name)
    icon = emj if use_emoji else txt
    if icon:
      break

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
class PerWarningResult(object):
  call_sites = attr.ib(factory=set)
  import_sites = attr.ib(factory=set)


def _collect_warning_result(outcome_msgs):
  """Collects issued warnings from all test outcomes and dedupes causes for
  each warning.
  """
  result = defaultdict(PerWarningResult)
  for outcome_msg in outcome_msgs:
    for _, test_result in iteritems(outcome_msg.test_results):
      for name, causes in iteritems(test_result.warnings):
        for cause in causes.causes:
          if cause.WhichOneof('oneof_cause') == 'call_site':
            result[name].call_sites.add(CallSite.from_cause_pb(cause))
          else:
            result[name].import_sites.add(ImportSite.from_cause_pb(cause))
  return result


def _print_warnings(warning_result, recipe_deps):
  def print_bug_links(definition):
    def construct_monorail_link(bug):
      return 'https://%s/p/%s/issues/detail?id=%d' % (
          bug.host, bug.project, bug.id)

    if definition.monorail_bug:
      if len(definition.monorail_bug) == 1:
        print('Bug Link: %s' % (
            construct_monorail_link(definition.monorail_bug[0]),))
      else:
        print('Bug Links:')
        for bug in definition.monorail_bug:
          print('  %s' % construct_monorail_link(bug))

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
                              key=lambda s: (s.repo, s.module, s.recipe)):
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
