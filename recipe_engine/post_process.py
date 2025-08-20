# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file contains post process filters for use with the
RecipeTestApi.post_process method in GenTests.
"""

from __future__ import annotations

from collections import defaultdict, OrderedDict, namedtuple
import re
from typing import Callable, Mapping, TYPE_CHECKING

from past.builtins import basestring
from recipe_engine import post_process_inputs

if TYPE_CHECKING:
  from recipe_engine.internal.test import magic_check_fn


_filterRegexEntry = namedtuple('_filterRegexEntry', 'at_most at_least fields')


class Filter:
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
    for name, step in step_odict.items():
      field_set = unused_includes.pop(name, None)
      if field_set is None:
        for exp, (_, _, fset) in re_data.items():
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
          k: v for k, v in step.to_step_dict().items()
          if k in field_set or k == 'name'
        }

    check(len(unused_includes) == 0)

    for regex, (at_least, at_most, _) in re_data.items():
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


def attach_recipe_warning(*warnings: str):
  """Attach a recipe warning to a post-process check.

  Don't immediately issue a recipe warning but simply attach it to the
  post-process check. When the check is added to a test with
  TestData.post_process() in recipe_test_api.py the warning will be issued.
  """
  def decorator(func):
    if not hasattr(func, 'recipe_warnings'):
      func.recipe_warnings = []
    func.recipe_warnings.extend(warnings)
    return func

  return decorator


def DoesNotRun(check, step_odict, *steps):
  """Asserts that the given steps don't run.

  Usage:
    yield api.test(..., api.post_process(DoesNotRun, 'step_a', 'step_b'))
  """
  banSet = set(steps)
  for step_name in step_odict:
    check(step_name not in banSet)


def DoesNotRunRE(check, step_odict, *step_regexes):
  """Asserts that no steps matching any of the regexes have run.

  Args:
    step_regexes (str) - The step name regexes to ban.

  Usage:
    yield api.test(
        ...,
        api.post_process(DoesNotRunRE, '.*with_patch.*', '.*compile.*'))

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
    yield api.test(..., api.post_process(MustRun, 'step_a', 'step_b'))
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
    yield api.test(...,
                   api.post_process(MustRunRE, r'.*with_patch.*', at_most=2))
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
    yield api.test(..., api.post_process(StepSuccess, 'step-name'))
  """
  check(step_odict[step].status == 'SUCCESS')


def StepWarning(check, step_odict, step):
  """Assert that a step has the warning status.

  Args:
    step (str) - The step to check for warning.

  Usage:
    yield api.test(..., api.post_process(StepWarning, 'step-name'))
  """
  check(step_odict[step].status == 'WARNING')


def StepFailure(check, step_odict, step):
  """Assert that a step failed.

  Args:
    step (str) - The step to check for a failure.

  Usage:
    yield api.test(..., api.post_process(StepFailure, 'step-name'))
  """
  check(step_odict[step].status == 'FAILURE')


def StepException(check, step_odict, step):
  """Assert that a step had an exception.

  Args:
    step (str) - The step to check for an exception.

  Usage:
    yield api.test(..., api.post_process(StepException, 'step-name'))
  """
  check(step_odict[step].status == 'EXCEPTION')


def StepCanceled(check, step_odict, step):
  """Assert that a step had an exception.

  Args:
    step (str) - The step to check for an exception.

  Usage:
    yield api.test(..., api.post_process(StepCanceled, 'step-name'))
  """
  check(step_odict[step].status == 'CANCELED')


def _fullmatch(pattern, string):
  m = re.match(pattern, string)
  return m and m.span()[1] == len(string)


def StepCommandEquals(check, step_odict, step, expected_cmd):
  """Assert that a step's command matches a given list of strings.

  Args:
    step (str) - The step to check the command of.
    expected_cmd (list(str)) - Strings to match the elements of the step's
      command.

  Usage:
    yield api.test(...,
                   api.post_process(StepCommandEquals, 'step-name',
                                    ['my', 'command']))
  """
  assert all((isinstance(elem, str) for elem in expected_cmd)), \
      'expected_cmd must be an iterable of strings'
  cmd = step_odict[step].cmd
  check(expected_cmd == cmd)


def StepCommandRE(check, step_odict, step, expected_patterns):
  """Assert that a step's command matches a given list of regular expressions.

  Args:
    step (str) - The step to check the command of.
    expected_patterns (list(str, re.Pattern)) - Regular expressions to match the
      elements of the step's command. The i-th element of the step's command
      will be matched against the i-th regular expression. If the pattern does
      not match the entire argument string, it is a CHECK failure.

  Usage:
    yield api.test(...,
                   api.post_process(StepCommandRE, 'step-name',
                                    ['my', 'command', '.*']))
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

  Usage:
    yield api.test(..., StepCommandContains, 'step-name', ['--force'])
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

  Usage:
    yield api.test(..., StepCommandDoesNotContain, 'step-name', ['--force'])
  """
  check(
      'command line for step %s does not contain  %s' %
      (step, argument_sequence), argument_sequence not in step_odict[step].cmd)


def StepCommandEmpty(check, step_odict, step):
  """Assert that a step ran no command.

  Args:
    step (str) - The name of the step to check the command of.

  Usage:
    yield api.test(..., api.post_process(StepCommandEmpty, 'step-name'))
  """
  check(not step_odict[step].cmd)


def StepTextEquals(check, step_odict, step, expected):
  """Assert that a step's step_text is equal to a given string.

  Args:
    step (str) - The step to check the step_text of.
    expected (str) - The expected value of the step_text.

  Usage:
    yield api.test(
        ..., api.post_process(StepTextEquals, 'step-name', 'expected-text'))
  """
  check(step_odict[step].step_text == expected)


def StepTextContains(check, step_odict, step, expected_substrs):
  """Assert that a step's step_text contains given substrings.

  Args:
    step (str) - The step to check the step_text of.
    expected_substrs (list(str)) - The expected substrings the step_text should
        contain.

  Usage:
    yield api.test(...,
                   api.post_process(StepTextContains, 'step-name',
                                    ['substr1', 'substr2']))
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
    yield api.test(
        ..., api.post_process(StepSummaryEquals, 'step-name', 'expected-text'))
  """
  check(step_odict[step].step_summary_text == expected)


def StepEnvContains(check, step_odict, step, env_dict):
  """Assert that a step's env contains the given key/value pairs.

  Args:
    step (str) - The name of the step to check the env of.
    env_dict (Dict[str, str]) - The expected key/value pairs to look for. The
      check will pass if the steps's env contains all of the given key/value
      pairs.

  Usage:
    yield api.test(
        ..., api.post_process(StepEnvContains, 'step-name', {'FOO': 'BAR'}))
  """
  for k, v in env_dict.items():
    check('env for step %s contained %s: %s' % (step, k, v),
          (k, v) in step_odict[step].env.items())


def StepEnvDoesNotContain(check, step_odict, step, env_dict):
  """Assert that a step's env does not contain the given key/value pairs.

  Args:
    step (str) - The name of the step to check the env of.
    env_dict (Dict[str, str]) - The key/value pairs that should not be present.
      The check will pass if the step's env does not contain any of the given
      key/value pairs.

  Usage:
    yield api.test(
        ...,
        api.post_process(StepEnvDoesNotContain, 'step-name', {'FOO': 'BAR'}))
  """
  for k, v in env_dict.items():
    check('env for step %s did not contain %s: %s' % (step, k, v),
          (k, v) not in step_odict[step].env.items())


def StepEnvEquals(check, step_odict, step, env_dict):
  """Assert that a step's env equals the given dict.

  Args:
    step (str) - The name of the step to check the env of.
    env_dict (Dict[str, str]) - The expected key/value pairs to look for. The
      check will pass if the given env_dict is equal to the step's env.

  Usage:
    yield api.test(
        ..., api.post_process(StepEnvEquals, 'step-name', {'FOO': 'BAR'}))
  """
  check('env for step %s equaled %s' % (step, env_dict),
        step_odict[step].env == env_dict)


def HasLog(check, step_odict, step, log):
  """Assert that a step contains a specific named log.

  Args:
    step (str) - The step to check the log of.
    log (str) - The name of the log to check.

  Usage:
    yield api.test(... api.post_process(HasLog, 'step-name', 'log-name'))
  """
  check(log in step_odict[step].logs)


def DoesNotHaveLog(check, step_odict, step, log):
  """Assert that a step does not contain a specific named log.

  Args:
    step (str) - The step to check the log of.
    log (str) - The name of the log to check.

  Usage:
    yield api.test(...,
                   api.post_process(DoesNotHaveLog, 'step-name', 'log-name'))
  """
  check(log not in step_odict[step].logs)


def LogEquals(check, step_odict, step, log, expected):
  """Assert that a step's log is equal to a given string.

  Args:
    step (str) - The step to check the log of.
    log (str) - The name of the log to check.
    expected (str) - The expected value of the log.

  Usage:
    yield api.test(
        ...,
        api.post_process(LogEquals, 'step-name', 'log-name', 'expected-text'))
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
    yield api.test(...,
                   api.post_process(LogEquals, 'step-name', 'log-name',
                                    ['substr1', 'substr2']))
  """
  assert not isinstance(expected_substrs, basestring), \
      'expected_substrs must be an iterable of strings and must not be a string'
  for expected in expected_substrs:
    check(expected in step_odict[step].logs[log])


def LogDoesNotContain(check, step_odict, step, log, unexpected_substrs):
  """Assert that a step's log does not contain given substrings.

  Args:
    step (str) - The step to check the log of.
    log (str) - The name of the log to check.
    unexpected_substrs (list(str)) - The unexpected substrings the log should
        not contain.

  Usage:
    yield api.test(
        ...,
        api.post_process(LogDoesNotContain, 'step-name', 'log-name',
                         ['substr1', 'substr2']))
  """
  assert not isinstance(unexpected_substrs, basestring), (
      'unexpected_substrs must be an iterable of strings and must not be a '
      'string')
  for unexpected in unexpected_substrs:
    check(unexpected not in step_odict[step].logs[log])


def HasLink(check, step_odict, step: str, link: str):
  """Check that the step has a link with the given name.

  Args:
    step - The step to check the links of
    link - The name of a link expected to exist

  Usage:
    yield api.test(
        ..., api.post_process(HasLink, 'step-name', 'link'))
  """
  check(step in step_odict)
  check(link in step_odict[step].links)


def DoesNotHaveLink(check, step_odict, step: str, link: str):
  """Check that the step does not have a link with the given name.

  Args:
    step - The step to check the links of
    link - The name of a link expected to not exist

  Usage:
    yield api.test(
        ..., api.post_process(DoesNotHaveLink, 'step-name', 'link'))
  """
  check(step in step_odict)
  check(link not in step_odict[step].links)


def HasLinkRE(check, step_odict, step: str, link: re.Pattern | str):
  """Check that the step has a link with the given name.

  Args:
    step - The step to check the links of
    link - A pattern of a link name expected to exist

  Usage:
    yield api.test(
        ..., api.post_process(HasLinkRE, 'step-name', r'link.*'))
  """
  check(step in step_odict)
  check(any(_fullmatch(link, x) for x in step_odict[step].links))


def DoesNotHaveLinkRE(check, step_odict, step: str, link: re.Pattern | str):
  """Check that the step link does not have a matching link name.

  Args:
    step - The step to check the links of
    link - A link name pattern expected to not match any links

  Usage:
    yield api.test(
        ..., api.post_process(DoesNotHaveLinkRE, 'step-name', r'link.*'))
  """
  check(step in step_odict)
  check(not any(_fullmatch(link, x) for x in step_odict[step].links))


def LinkEquals(check, step_odict, step: str, link: str, expected: str):
  """Check that the step link has the given value.

  Args:
    step - The step to check the links of
    link - The name of the link
    dest - The expected destination of the link

  Usage:
    yield api.test(
        ...,
        api.post_process(
            LinkEquals,
            'step-name',
            'link',
            'http://example.com',
        ),
    )
  """
  check(step in step_odict)
  check(link in step_odict[step].links)
  check(step_odict[step].links[link] == expected)


def LinkEqualsRE(
    check, step_odict, step: str, link: str, expected: str | re.Pattern
):
  """Check that the step link has a matching value.

  Args:
    step - The step to check the links of
    link - The name of the link
    dest - The expected destination of the link

  Usage:
    yield api.test(
        ...,
        api.post_process(
            LinkEqualsRE,
            'step-name',
            'link',
            'http://example.com',
        ),
    )
  """
  check(step in step_odict)
  check(link in step_odict[step].links)
  check(_fullmatch(expected, step_odict[step].links[link]))


def GetBuildProperties(step_odict):
  """Retrieves the build properties for a recipe."""
  build_properties = {}
  for name, step in step_odict.items():
    if name == '$result':
      continue
    for prop, value in step.output_properties.items():
      build_properties[prop] = value
  return build_properties


def PropertyEquals(check, step_odict, key, value):
  """Assert that a recipe's output property `key` equals `value`.

  Args:
    key (str) - The key to look for in output properties.
    value (jsonish) - The value to look for in output properties.

  Usage:
    yield api.test(..., api.post_process(PropertyEquals, 'do_not_retry', True))
  """
  build_properties = GetBuildProperties(step_odict)

  # Short circuiting of boolean expressions is broken in check().
  # https://crbug.com/946015.
  if check(key in build_properties):
    check(build_properties[key] == value)


def PropertyMatchesRE(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    key: str,
    pattern: str | re.Pattern,
):
  """Assert that a recipe's output property `key` value matches `pattern`.

  Args:
    key - The key to look for in output properties.
    pattern - The pattern for comparison.

  Usage:
    yield api.test(
        ...,
        api.post_process(PropertyMatchesRE, 'key', r'.*value.*'),
    )
  """
  build_properties = GetBuildProperties(step_odict)

  if check(key in build_properties):
    if check(isinstance(build_properties[key], str)):
      check(re.search(pattern, build_properties[key]))


def PropertyMatchesCallable(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    key: str,
    matcher: Callable[[magic_check_fn.Checker, Any], bool],
):
  """Assert that a recipe's output property `key` meets conditions of `matcher`.

  Args:
    key - The key to look for in output properties.
    matcher - A callable that evaluates the property.

  Usage:
    yield api.test(
        ...,
        api.post_process(
            PropertyMatchesCallable,
            'key',
            lambda check, x: check('foo' in x),
        ),
    )
  """
  build_properties = GetBuildProperties(step_odict)

  if check(key in build_properties):
    check(matcher(check, build_properties[key]))


def PropertiesContain(check, step_odict, key):
  """Assert that a recipe's output properties contain `key`.

  Args:
    key (str) - The key to check for.

  Usage:
    yield api.test(..., api.post_process(PropertiesContain, 'property_key'))
  """
  build_properties = GetBuildProperties(step_odict)
  check(key in build_properties)

def PropertiesDoNotContain(check, step_odict, key):
  """Assert that a recipe's output properties do not contain `key`.

  Args:
    key (str) - The key to check for.

  Usage:
    yield api.test(...,
                   api.post_process(PropertiesDoNotContain, 'property_key'))
  """
  build_properties = GetBuildProperties(step_odict)
  check(key not in build_properties)


def NumTagsEquals(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    step_name: str,
    count: int,
) -> None:
  """Asserts that the given step has count tags.

  Args:
    step_name - The step expected to contain tags.
    count - The number of tags expected to exist.

  Usage:
    yield api.test(..., api.post_process(HasTag, 'step', 2))
  """
  if check(step_name in step_odict):
    step = step_odict[step_name]
    check(len(step.tags) == count)


def HasTag(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    step_name: str,
    *tag: str,
) -> None:
  """Asserts that tags with the given names are attached to the given step.

  Args:
    step_name - The step expected to contain tags.
    tag - The tags expected to exist.

  Usage:
    yield api.test(..., api.post_process(HasTag, 'step', 'tag_1', 'tag_2'))
  """
  if check(step_name in step_odict):
    step = step_odict[step_name]
    for t in tag:
      check(t in step.tags)


def LacksTag(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    step_name: str,
    *tag: str,
) -> None:
  """Asserts that tags with the given names are not attached to the given step.

  Args:
    step_name - The step expected to contain tags.
    tag - The tags expected to not exist.

  Usage:
    yield api.test(..., api.post_process(HasTag, 'step', 'tag_1', 'tag_2'))
  """
  if check(step_name in step_odict):
    step = step_odict[step_name]
    for t in tag:
      check(t not in step.tags)


def TagEquals(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    step_name: str,
    tag: str,
    value: str,
) -> None:
  """Asserts that a tag on the given step has the given value.

  Args:
    step_name - The step expected to contain tags.
    tag - The tag name.
    value - The expected tag value.

  Usage:
    yield api.test(..., api.post_process(HasEquals, 'step', 'tag', 'value'))
  """
  if check(step_name in step_odict):
    step = step_odict[step_name]
    if check(tag in step.tags):
      check(step.tags[tag] == value)


def TagMatchesRE(
    check: magic_check_fn.Checker,
    step_odict: Mapping[str, post_process_inputs.Step],
    step_name: str,
    tag: str,
    pattern: str | re.Pattern,
) -> None:
  """Asserts that a tag on the given step matches the pattern.

  Args:
    step_name - The step expected to contain tags.
    tag - The tag name.
    value - The expected tag value.

  Usage:
    yield api.test(..., api.post_process(HasEquals, 'step', 'tag', 'value'))
  """
  if check(step_name in step_odict):
    step = step_odict[step_name]
    if check(tag in step.tags):
      check(re.search(pattern, step.tags[tag]))


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


def SummaryMarkdown(check, step_odict, summary):
  """Assert that recipe output summary is the same as the given summary.

  Args:
    summary (str): the string to match.

  Usage:
    yield api.test(..., api.post_process(SummaryMarkdown, 'summary'))
  """
  result = step_odict['$result']
  actual_summary = result.get('failure').get('humanReason') if (
      result.get('failure')) else result.get('summaryMarkdown')
  if not check('recipe doesn\'t output any summary',
               actual_summary):
    return
  check(
      'expected recipe output summary %r (found summary %r instead)' %
      (summary, actual_summary), summary == actual_summary)


def SummaryMarkdownRE(check, step_odict, summary_regex):
  """Assert that recipe output summary matches given regex.

  Args:
    summary_regex (str): the regular expression to match.

  Usage:
    yield api.test(..., api.post_process(SummaryMarkdownRE, 'summary: .*'))
  """
  result = step_odict['$result']
  actual_summary = result.get('failure').get('humanReason') if (
      result.get('failure')) else result.get('summaryMarkdown')
  if not check('recipe doesn\'t output any summary',
               actual_summary):
    return
  check(
      'expected recipe output summary matches %r (found summary %r instead)' %
      (summary_regex, actual_summary), re.search(summary_regex, actual_summary))


def DropExpectation(_check, step_odict, *prefixes):
  """Using this post-process hook will drop expectations for this test.

  With no arguments this must be the last post-process check—there will be no
  steps left for other post-process checks to evaluate.

  With arguments, this will only drop steps that begin with those exact
  prefixes. Specifically, where the full name of the step or one of its parents
  matches the given prefix.

  For example "abc.def" matches prefix "abc" if "abc" is a parent step and
  "def" is a child, but not if "abc.def" is a top-level step. An example is at
  https://chromium.googlesource.com/infra/luci/recipes-py/+/main/recipe_modules/step/tests/drop_expectation.expected/basic.json.

  Usage:
    yield api.test(..., api.post_process(DropExpectation))
    yield api.test(..., api.post_process(DropExpectation, 'checkout'))
  """
  if not prefixes:
    return {}

  result_steps = OrderedDict()
  step_stack = []

  for name, step in step_odict.items():
    if not isinstance(step, post_process_inputs.Step):
      result_steps[name] = step
      continue

    step_stack = step_stack[0:step.nest_level]
    step_stack.append(name)

    for prefix in prefixes:
      if prefix in step_stack:
        break
    else:
      result_steps[name] = step

  return result_steps
