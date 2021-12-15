# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file contains post process filters for use with the
RecipeTestApi.post_process method in GenTests.
"""

from past.builtins import basestring
from future.utils import iteritems

import re

from collections import defaultdict, OrderedDict, namedtuple


_filterRegexEntry = namedtuple('_filterRegexEntry', 'at_most at_least fields')


class Filter(object):
  """Filter is an implementation of a post_process callable which can remove
  unwanted data from a step OrderedDict."""

  def __init__(self, *steps):
    """Builds a new Filter object. It may be optionally prepopulated by
    specifying steps.

    Usage:
      f = Filter('step_a', 'step_b')
      yield TEST + api.post_process(f)

      f = f.include('other_step')
      yield TEST + api.post_process(f)

      yield TEST + api.post_process(Filter('step_a', 'step_b', 'other_step'))
    """
    self.data = {name: () for name in steps}
    self.re_data = {}

  def __call__(self, check, step_odict):
    unused_includes = self.data.copy()
    re_data = self.re_data.copy()

    re_usage_count = defaultdict(int)

    to_ret = OrderedDict()
    for name, step in iteritems(step_odict):
      field_set = unused_includes.pop(name, None)
      if field_set is None:
        for exp, (_, _, fset) in iteritems(re_data):
          if exp.match(name):
            re_usage_count[exp] += 1
            field_set = fset
            break
      if field_set is None:
        continue
      if len(field_set) == 0:
        to_ret[name] = step
      else:
        to_ret[name] = {
          k: v for k, v in iteritems(step.to_step_dict())
          if k in field_set or k == 'name'
        }

    check(len(unused_includes) == 0)

    for regex, (at_least, at_most, _) in iteritems(re_data):
      check(re_usage_count[regex] >= at_least)
      if at_most is not None:
        check(re_usage_count[regex] <= at_most)

    return to_ret

  def include(self, step_name, fields=()):
    """Include adds a step to the included steps set.

    Additionally, if any specified fields are provided, they will be the total
    set of fields in the filtered step. The 'name' field is always included. If
    fields is omitted, the entire step will be included.

    Args:
      step_name (str) - The name of the step to include
      fields (list(str)) - The field(s) to include. Omit to include all fields.

    Returns the new filter.
    """
    if isinstance(fields, basestring):
      raise ValueError('Expected fields to be a non-string iterable')
    new_data = self.data.copy()
    new_data[step_name] = frozenset(fields)
    ret = Filter()
    ret.data = new_data
    ret.re_data = self.re_data
    return ret

  def include_re(self, step_name_re, fields=(), at_least=1, at_most=None):
    """This includes all steps which match the given regular expression.

    If a step matches both an include() directive as well as include_re(), the
    include() directive will take precedence.

    Args:
      step_name_re (str or regex) - the regular expression of step names to
        match.
      fields (list(str)) - the field(s) to include in the matched steps. Omit to
        include all fields.
      at_least (int) - the number of steps that this regular expression MUST
        match.
      at_most (int) - the maximum number of steps that this regular expression
        MUST NOT exceed.

    Returns the new filter.
    """
    if isinstance(fields, basestring):
      raise ValueError('Expected fields to be a non-string iterable')
    new_re_data = self.re_data.copy()
    new_re_data[re.compile(step_name_re)] = _filterRegexEntry(
      at_least, at_most, frozenset(fields))

    ret = Filter()
    ret.data = self.data
    ret.re_data = new_re_data
    return ret


def DoesNotRun(check, step_odict, *steps):
  """Asserts that the given steps don't run.

  Usage:
    yield TEST + api.post_process(DoesNotRun, 'step_a', 'step_b')

  """
  banSet = set(steps)
  for step_name in step_odict:
    check(step_name not in banSet)


def DoesNotRunRE(check, step_odict, *step_regexes):
  """Asserts that no steps matching any of the regexes have run.

  Args:
    step_regexes (str) - The step name regexes to ban.

  Usage:
    yield TEST + api.post_process(DoesNotRunRE, '.*with_patch.*', '.*compile.*')

  """
  step_regexes = [re.compile(r) for r in step_regexes]
  for step_name in step_odict:
    for r in step_regexes:
      check(not r.match(step_name))


def MustRun(check, step_odict, *steps):
  """Asserts that steps with the given names are in the expectations.

  Args:
    steps (str) - The steps that must have run.

  Usage:
    yield TEST + api.post_process(MustRun, 'step_a', 'step_b')
  """
  for step_name in steps:
    check(step_name in step_odict)


def MustRunRE(check, step_odict, step_regex, at_least=1, at_most=None):
  """Assert that steps matching the given regex completely are in the
  expectations.

  Args:
    step_regex (str, compiled regex) - The regular expression to match.
    at_least (int) - Match at least this many steps. Matching fewer than this
      is a CHECK failure.
    at_most (int) - Optional upper bound on the number of matches. Matching
      more than this is a CHECK failure.

  Usage:
    yield TEST + api.post_process(MustRunRE, r'.*with_patch.*', at_most=2)
  """
  step_regex = re.compile(step_regex)
  matches = 0
  for step_name in step_odict:
    if step_regex.match(step_name):
      matches += 1
  check(matches >= at_least)
  if at_most is not None:
    check(matches <= at_most)


def StepSuccess(check, step_odict, step):
  """Assert that a step succeeded.

  Args:
    step (str) - The step to check for success.

  Usage:
    yield (
        TEST
        + api.post_process(StepSuccess, 'step-name')
    )
  """
  check(step_odict[step].status == 'SUCCESS')


def StepWarning(check, step_odict, step):
  """Assert that a step has the warning status.

  Args:
    step (str) - The step to check for warning.

  Usage:
    yield (
        TEST
        + api.post_process(StepWarning, 'step-name')
    )
  """
  check(step_odict[step].status == 'WARNING')


def StepFailure(check, step_odict, step):
  """Assert that a step failed.

  Args:
    step (str) - The step to check for a failure.

  Usage:
    yield (
        TEST
        + api.post_process(StepFailure, 'step-name')
    )
  """
  check(step_odict[step].status == 'FAILURE')


def StepException(check, step_odict, step):
  """Assert that a step had an exception.

  Args:
    step (str) - The step to check for an exception.

  Usage:
    yield (
        TEST
        + api.post_process(StepException, 'step-name')
    )
  """
  check(step_odict[step].status == 'EXCEPTION')


def StepCanceled(check, step_odict, step):
  """Assert that a step had an exception.

  Args:
    step (str) - The step to check for an exception.

  Usage:
    yield (
        TEST
        + api.post_process(StepCanceled, 'step-name')
    )
  """
  check(step_odict[step].status == 'CANCELED')


def _fullmatch(pattern, string):
  m = re.match(pattern, string)
  return m and m.span()[1] == len(string)


def StepCommandRE(check, step_odict, step, expected_patterns):
  """Assert that a step's command matches a given list of regular expressions.

  Args:
    step (str) - The step to check the command of.
    expected_patterns (list(str, re.Pattern)) - Regular expressions to match the
      elements of the step's command. The i-th element of the step's command
      will be matched against the i-th regular expression. If the pattern does
      not match the entire argument string, it is a CHECK failure.

  Usage:
    yield (
        TEST
        + api.post_process(StepCommandRE, 'step-name',
                           ['my', 'command', '.*'])
    )
  """
  cmd = step_odict[step].cmd
  for expected, actual in zip(expected_patterns, cmd):
    check(_fullmatch(expected, actual))
  unmatched = cmd[len(expected_patterns):]
  check('all arguments matched', not unmatched)
  unused = expected_patterns[len(cmd):]
  check('all patterns used', not unused)

def StepCommandContains(check, step_odict, step, argument_sequence):
  """Assert that a step's command contained the given sequence of arguments.

  Args:
    step (str) - The name of the step to check the command of.
    argument_sequence (list of (str|regex)) - The expected sequence of
      arguments. Strings will be compared for equality, while regex patterns
      will be matched using the search method. The check will pass if the step's
      command contains a subsequence where the elements are matched by the
      corresponding elements of argument_sequence.
  """
  check('command line for step %s contained %s' % (step, argument_sequence),
        argument_sequence in step_odict[step].cmd)


def StepCommandDoesNotContain(check, step_odict, step, argument_sequence):
  """Assert that a step's command does not contain the given sequence of
  arguments.

  Args:
    step (str) - The name of the step to check the command of.
    argument_sequence (list of (str|regex)) - The sequence of arguments that
      should not exist. The check will fail if the step's command contains a
      subsequence where the elements are matched by the corresponding elements
      of argument_sequence.
  """
  check(
      'command line for step %s does not contain  %s' %
      (step, argument_sequence), argument_sequence not in step_odict[step].cmd)


def StepTextEquals(check, step_odict, step, expected):
  """Assert that a step's step_text is equal to a given string.

  Args:
    step (str) - The step to check the step_text of.
    expected (str) - The expected value of the step_text.

  Usage:
    yield TEST + api.post_process(StepTextEquals, 'step-name', 'expected-text')
  """
  check(step_odict[step].step_text == expected)


def StepTextContains(check, step_odict, step, expected_substrs):
  """Assert that a step's step_text contains given substrings.

  Args:
    step (str) - The step to check the step_text of.
    expected_substrs (list(str)) - The expected substrings the step_text should
        contain.

  Usage:
    yield (
        TEST
        + api.post_process(StepTextContains, 'step-name',
                           ['substr1', 'substr2'])
    )
  """
  assert not isinstance(expected_substrs, basestring), \
      'expected_substrs must be an iterable of strings and must not be a string'
  for expected in expected_substrs:
    check(expected in step_odict[step].step_text)


def StepSummaryEquals(check, step_odict, step, expected):
    """Check that the step's step_summary_text equals given value.

    Args:
      step (str) - The step to check the step_text of
      expected (str) - The expected value of the step_text

    Usage:
      yield TEST + \
          api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_summary_text == expected)


def LogEquals(check, step_odict, step, log, expected):
  """Assert that a step's log is equal to a given string.

  Args:
    step (str) - The step to check the log of.
    log (str) - The name of the log to check.
    expected (str) - The expected value of the log.

  Usage:
    yield (
        TEST
         + api.post_process(LogEquals, 'step-name', 'log-name', 'expected-text')
    )
  """
  check(step_odict[step].logs[log] == expected)


def LogContains(check, step_odict, step, log, expected_substrs):
  """Assert that a step's log contains given substrings.

  Args:
    step (str) - The step to check the log of.
    log (str) - The name of the log to check.
    expected_substrs (list(str)) - The expected substrings the log should
        contain.

  Usage:
    yield (
        TEST
         + api.post_process(LogEquals, 'step-name', 'log-name',
                            ['substr1', 'substr2'])
    )
  """
  assert not isinstance(expected_substrs, basestring), \
      'expected_substrs must be an iterable of strings and must not be a string'
  for expected in expected_substrs:
    check(expected in step_odict[step].logs[log])


def GetBuildProperties(step_odict):
  """Retrieves the build properties for a recipe."""
  build_properties = {}
  for name, step in iteritems(step_odict):
    if name == '$result':
      continue
    for prop, value in iteritems(step.output_properties):
      build_properties[prop] = value
  return build_properties


def PropertyEquals(check, step_odict, key, value):
  """Assert that a recipe's output property `key` equals `value`.

  Args:
    key (str) - The key to look for in output properties.
    value (jsonish) - The value to look for in output properties.

  Usage:
    yield (
        TEST
         + api.post_process(PropertyEquals, 'do_not_retry', True)
    )
  """
  build_properties = GetBuildProperties(step_odict)

  # Short circuiting of boolean expressions is broken in check().
  # https://crbug.com/946015.
  if check(key in build_properties):
    check(build_properties[key] == value)


def PropertiesDoNotContain(check, step_odict, key):
  """Assert that a recipe's output properties do not contain `key`.

  Args:
    key (str) - The key to check for.

  Usage:
    yield (
        TEST
         + api.post_process(PropertiesDoNotContain, 'property_key')
    )
  """
  build_properties = GetBuildProperties(step_odict)
  check(key not in build_properties)


def StatusCodeIn(check, step_odict, *codes):
  """Assert that recipe result status code is within expected codes.

  DEPRECATED: Use StatusSuccess or StatusFailure instead.

  Args:
    codes (list): list of expected status codes (int).
  """
  check(len(codes) == 1)
  code = codes[0]

  check(code in (0, 1, 2))
  if code == 0:
    StatusSuccess(check, step_odict)
  else:
    StatusAnyFailure(check, step_odict)


def StatusSuccess(check, step_odict):
  """Assert that the recipe finished successfully."""
  failure = step_odict['$result'].get('failure')
  check('recipe succeeded (found failure instead)', failure is None)


def StatusAnyFailure(check, step_odict):
  """Assert that the recipe failed."""
  check('recipe failed (found success instead)',
        'failure' in step_odict['$result'])


def StatusFailure(check, step_odict):
  """Assert that the recipe had a non-infra failure."""
  result = step_odict['$result']
  if not check('recipe failed (found success instead)', 'failure' in result):
    return
  check('expected failure but recipe had infra failure',
        'failure' in result['failure'])


def StatusException(check, step_odict):
  """Assert that the recipe had an infra failure."""
  result = step_odict['$result']
  if not check('recipe had infra failure (found success instead)',
               'failure' in result):
    return
  check('recipe had infra failure (found non-infra failure instead)',
        'failure' not in result['failure'])


def ResultReason(check, step_odict, reason):
  """Assert that recipe result reason matches given reason.

  Args:
    reason (str): the string to match.
  """
  result = step_odict['$result']
  if not check('recipe failed with reason %r (found success instead)' % reason,
               'failure' in result):
    return
  if not check('recipe failed with reason %r (found no failure reason)',
               'humanReason' in result['failure']):
    return
  actual_reason = result['failure']['humanReason']
  check(
      'recipe failed with reason %r (found reason %r instead)' %
      (reason, actual_reason), reason == actual_reason)


def ResultReasonRE(check, step_odict, reason_regex):
  """Assert that recipe result reason contains given regex.

  Args:
    reason_regex (str): the regular expression to match.
  """
  result = step_odict['$result']
  if not check(
      'recipe failed with reason containing %r (found success instead)',
      'failure' in result):
    return
  if not check(
      ('recipe failed with reason containing %r (found no failure reason '
       'instead)'), 'humanReason' in result['failure']):
    return
  actual_reason = result['failure']['humanReason']
  check(
      'recipe failed with reason containing %r (found reason %r instead)' %
      (reason_regex, actual_reason), re.search(reason_regex, actual_reason))


def DropExpectation(_check, _step_odict):
  """Using this post-process hook will drop the expectations for this test
  completely.

  Usage:
    yield TEST + api.post_process(DropExpectation)

  """
  return {}
