# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file contains post process filters for use with the
RecipeTestApi.post_process method in GenTests.
"""

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
    for name, step in step_odict.iteritems():
      field_set = unused_includes.pop(name, None)
      if field_set is None:
        for exp, (_, _, fset) in re_data.iteritems():
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
          k: v for k, v in step.iteritems()
          if k in field_set or k == 'name'
        }

    check(len(unused_includes) == 0)

    for regex, (at_least, at_most, _) in re_data.iteritems():
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
  exepectations.

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


def _check_step_was_run(check, step_odict, step):
  return check('step %s was run' % step, step in step_odict)


def _extract_step_status(check, step_odict, step):
  """Extract the status for a step.

  The check function is used to check that the step was actually run.

  Args:
    step (str) - The name of the step to extract the status for.

  Returns:
    A string containing one of the following values: 'success', 'failure' or
    'exception'. If the given step was not run, None will be returned.
  """
  if not _check_step_was_run(check, step_odict, step):
    return
  for a in step_odict[step].get('~followup_annotations', []):
    if a == '@@@STEP_EXCEPTION@@@':
      return 'exception'
    if a == '@@@STEP_FAILURE@@@':
      return 'failure'
  return 'success'

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
  status = _extract_step_status(check, step_odict, step)
  if status is None:
    return
  check('step %s was success' % step, status == 'success')

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
  status = _extract_step_status(check, step_odict, step)
  if status is None:
    return
  check('step %s was failure' % step, status == 'failure')

def StepException(check, step_odict, step):
  """Assert that a step had an exception.

  Args:
    step (str) - The step to check for an exception.

  Usage:
    yield (
        TEST
        + api.post_process(Step, 'step-name')
    )
  """
  status = _extract_step_status(check, step_odict, step)
  if status is None:
    return
  check('step %s was exception' % step, status == 'exception')


def _check_cmd_was_in_step(check, step_odict, step):
  return check('step %s had a command' % step, 'cmd' in step_odict[step])

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
  if not _check_step_was_run(check, step_odict, step):
    return
  if not _check_cmd_was_in_step(check, step_odict, step):
    return
  cmd = step_odict[step]['cmd']
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
    argument_sequence (list of str) - The expected sequence of arguments.
      Does not need to contain all of the command's arguments.
      Arguments in the sequence are expected to be found consecutively and
      in order.
  """
  def subsequence(containing, contained):
    for i in xrange(len(containing) - len(contained) + 1):
      if containing[i:i+len(contained)] == contained:
        return True
    return False

  if not _check_step_was_run(check, step_odict, step):
    return
  if not _check_cmd_was_in_step(check, step_odict, step):
    return
  step_cmd = step_odict[step]['cmd']
  check('command line for step %s contained %s' % (
            step, argument_sequence),
        subsequence(step_cmd, argument_sequence))

_STEP_TEXT_RE = re.compile('@@@STEP_TEXT@(?P<text>.*)@@@$')


def _extract_step_text(check, step_odict, step):
  """Extract the step_text for a step.

  The check function is used to check that the step was actually run.

  Args:
    step (str) - The name of the step to extract the step_text for.

  Returns:
    The step_text for the given step ('' if the a folloup annotation for the
    step's step_text was not found). If the given step was not run, None will
    be returned.
  """
  if not _check_step_was_run(check, step_odict, step):
    return
  for a in step_odict[step].get('~followup_annotations', []):
    match = _STEP_TEXT_RE.match(a)
    if match:
      return match.group('text')
  return ''


def StepTextEquals(check, step_odict, step, expected):
  """Assert that a step's step_text is equal to a given string.

  Args:
    step (str) - The step to check the step_text of.
    expected (str) - The expected value of the step_text.

  Usage:
    yield TEST + api.post_process(StepTextEquals, 'step-name', 'expected-text')
  """
  actual = _extract_step_text(check, step_odict, step)
  if actual is None:
    return
  check(actual == expected)


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
  actual = _extract_step_text(check, step_odict, step)
  if actual is None:
    return
  for expected in expected_substrs:
    check(expected in actual)


_LOG_LINE_RE = re.compile('@@@STEP_LOG_LINE@(?P<log>[^@]*)@(?P<text>.*)@@@$')
_LOG_END_RE = re.compile('@@@STEP_LOG_END@(?P<log>.*)@@@$')


def _extract_log(check, step_odict, step, log):
  """Extract a log for a step.

  The check function is used to check that the step was actually run and that a
  log with the given name was created for the step.

  Args:
    step (str) - The name of the step to extract a log for.
    log (str) - The name of the log to extract.

  Returns:
    The log identified by the step and log parameters as a single string with
    lines joined by \n. If the given step was not run or does not have the given
    log, None will be returned.
  """
  if not _check_step_was_run(check, step_odict, step):
    return
  log_lines = []
  for a in step_odict[step].get('~followup_annotations', []):
    match = _LOG_LINE_RE.match(a)
    if match and match.group('log') == log:
      log_lines.append(match.group('text'))
      continue
    match = _LOG_END_RE.match(a)
    if match and match.group('log') == log:
      log_lines.append('')
      break
  if not check('step %s has log %s' % (step, log), log_lines):
    return
  return '\n'.join(log_lines)


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
  actual = _extract_log(check, step_odict, step, log)
  if actual is None:
    return
  check(actual == expected)


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
  actual = _extract_log(check, step_odict, step, log)
  if actual is None:
    return
  for expected in expected_substrs:
    check(expected in actual)


def AnnotationContains(check, step_odict, step, expected_substrs):
  """Assert that a step's annotations contains given substrings.

  Args:
    step (str) - The step to check the annotations of.
    expected_substrs (list(str)) - The expected substrings the annotations
        should contain.

  Usage:
    yield (
        TEST
         + api.post_process(AnnotationContains, 'step-name',
                            ['substr1', 'substr2'])
    )
  """
  assert not isinstance(expected_substrs, basestring), \
      'expected_substrs must be an iterable of strings and must not be a string'

  if not check('step %s was run' % step, step in step_odict):
    return
  annotations = '\n'.join(step_odict[step].get('~followup_annotations', []))

  for expected in expected_substrs:
    check(expected in annotations)


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
  check(not 'failure' in step_odict['$result'])


def StatusAnyFailure(check, step_odict):
  """Assert that the recipe failed."""
  check('failure' in step_odict['$result'])


def StatusFailure(check, step_odict):
  """Assert that the recipe failed."""
  if check('failure' in step_odict['$result']):
    check('exception' not in step_odict['$result']['failure'])


def StatusException(check, step_odict):
  """Assert that the recipe failed."""
  if check('failure' in step_odict['$result']):
    check('exception' in step_odict['$result']['failure'])


def ResultReasonRE(check, step_odict, reason_regex):
  """Assert that recipe result reason matches given regex.

  Args:
    reason_regex (str): the regular expression to match.
  """
  result = step_odict['$result']
  if not check('failure' in result):
    return
  if not check('humanReason' in result['failure']):
    return
  check(re.match(reason_regex, result['failure']['humanReason']))


def DropExpectation(_check, _step_odict):
  """Using this post-process hook will drop the expectations for this test
  completely.

  Usage:
    yield TEST + api.post_process(DropExpectation)

  """
  return {}
