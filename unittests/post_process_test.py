#!/usr/bin/env vpython3
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


from __future__ import annotations

import collections
from typing import Any, Callable, OrderedDict

import test_env

from recipe_engine import post_process
from recipe_engine.internal.test import magic_check_fn
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.recipe_engine.internal.test.runner import Outcome


def make_step(name: str, *fields: str) -> dict[str, Any]:
  """Create a step dict containing the given fields and reasonable defaults.

  Args:
    name: The name of the step.
    fields: Names of step fields to include, such as 'cmd', 'cwd', 'env'. If not
      specified, then all default fields will be included.

  Returns:
    A dict representing a step, containing reasonable defaults for the given
    fields.
  """
  ret = {
    'name': name,
    'cmd': ['thing', 'other'],
    'cwd': 'some-directory',
    'env': {'var': 'value'},
  }
  if fields:
    return {k: v for k, v in ret.items() if k in fields or k == 'name'}
  return ret


def make_step_dict(*names: str) -> OrderedDict[str, dict[str, Any]]:
  """Create an OrderedDict of step dicts with given names and default fields.

  Args:
    names: Step names to include.

  Returns:
    An ordered dict of {step name: step dict}, in the same order that steps
    were provided. Each step dict will contain reasonable default values for
    fields such as 'cmd'.
  """
  return collections.OrderedDict([(name, make_step(name)) for name in names])


class PostProcessUnitTest(test_env.RecipeEngineUnitTest):
  """Helper class for testing post_process functions."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case.

    Subclasses should override this property to set a step dict that makes sense
    for the given test case.

    Raises:
      NotImplementedError: If not overridden by subclasses.
    """
    raise NotImplementedError()

  def post_process(self, func: Callable, *args,
                   **kwargs) -> tuple[Any, list[list[str]]]:
    """Run the given post_process function with self.step_dict.

    Args:
      func: A post_process checker function, such as MustRun.
      *args: Additional positional args for post_process.
      **kwargs: Additional keyword args for post-process.

    Returns:
      A tuple (expectations, failures), where expectations is as returned by
      magic_check_fn.post_process, and failures is a list of failures returned
      by the check, each represented by a list of output strings.
    """
    test_data = RecipeTestApi(None).post_process(func, *args, **kwargs)
    results = Outcome.Results()
    expectations = magic_check_fn.post_process(results, self.step_dict,
                                               test_data)
    return expectations, results.check

  def expect_pass(self, func: Callable, *args, **kwargs) -> None:
    """Assert that the given post_process func passes.

    The given function will be called with self.step_dict.

    Args:
      func: The post_process checker function, such as MustRun.
      *args: Additional positional args for the post_process call.
      **kwargs: Additional keyword args for the post_process call.

    Raises:
      AssertionError: If the post_process check raised any failures.
    """
    _, failures = self.post_process(func, *args, **kwargs)
    self.assertEqual(len(failures), 0)

  def expect_fails(self, num_fails: int, func: Callable, *args,
                   **kwargs) -> list[list[str]]:
    """Assert that the post_process func fails the expected number of times.

    The given function will be called with self.step_dict.

    Args:
      num_fails: The number of failures expected.
      func: The post_process checker function, such as MustRun.
      *args: Additional positional args for the post_process call.
      **kwargs: Additional keyword args for the post_process call.

    Returns:
      A list of failures, each represented as a list of output lines.

    Raises:
      AssertionError: If the post_process did not raise exactly the expected
      number of failures.
    """
    _, failures = self.post_process(func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def assertHas(self, failure: list[str], *text: str) -> None:
    """Assert that the given failure contains all the given strings.

    Args:
      failure: A failed post_process check, as a list of output lines.
      *text: Strings that must be contained by the concatenated failure message.

    Raises:
      AssertionError: If the failure message does not contain each of *text
    """
    combined = '\n'.join(failure.lines)
    for item in text:
      self.assertIn(item, combined)


class TestFilter(PostProcessUnitTest):
  """Test case for post_process.Filter."""
  f = post_process.Filter

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return make_step_dict('a', 'b', 'b.sub', 'b.sub2')

  def test_basic(self):
    results, failures = self.post_process(self.f('a', 'b'))
    self.assertEqual(results, list(make_step_dict('a', 'b').values()))
    self.assertEqual(len(failures), 0)

  def test_built(self):
    f = self.f()
    f = f.include('b')
    f = f.include('a')
    results, failures = self.post_process(f)
    self.assertEqual(results, list(make_step_dict('a', 'b').values()))
    self.assertEqual(len(failures), 0)

  def test_built_fields(self):
    f = self.f()
    f = f.include('b', ['env'])
    f = f.include('a', ['cmd'])
    results, failures = self.post_process(f)
    self.assertEqual(results, [make_step('a', 'cmd'), make_step('b', 'env')])
    self.assertEqual(len(failures), 0)

  def test_built_extra_includes(self):
    f = self.f('a', 'b', 'x')
    results, failures = self.post_process(f)
    self.assertEqual(results, list(make_step_dict('a', 'b').values()))
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[0],
                   'check((len(unused_includes) == 0))',
                   "unused_includes: {'x': ()}")

  def test_re(self):
    f = self.f().include_re(r'b\.')
    results, failures = self.post_process(f)
    self.assertEqual(results, list(make_step_dict('b.sub', 'b.sub2').values()))
    self.assertEqual(len(failures), 0)

  def test_re_low_limit(self):
    f = self.f().include_re(r'b\.', at_least=3)
    results, failures = self.post_process(f)
    self.assertEqual(results, list(make_step_dict('b.sub', 'b.sub2').values()))
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[-1], 'check((re_usage_count[regex] >= at_least))',
                   'at_least: 3', 're_usage_count[regex]: 2',
                   'regex: re.compile(\'b\\\\.\'')

  def test_re_high_limit(self):
    f = self.f().include_re(r'b\.', at_most=1)
    results, failures = self.post_process(f)
    self.assertEqual(results, list(make_step_dict('b.sub', 'b.sub2').values()))
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[0], 'check((re_usage_count[regex] <= at_most))')
    self.assertHas(failures[0], 'at_most: 1', 're_usage_count[regex]: 2',
                   'regex: re.compile(\'b\\\\.\'')


class TestRun(PostProcessUnitTest):
  """Test case for checks relating to which steps run."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return make_step_dict('a', 'b', 'b.sub', 'b.sub2')

  def test_mr_pass(self):
    self.expect_pass(post_process.MustRun, 'a')

  def test_mr_fail(self):
    self.expect_fails(1, post_process.MustRun, 'x')

  def test_mr_pass_re(self):
    self.expect_pass(post_process.MustRunRE, 'a')
    self.expect_pass(post_process.MustRunRE, 'a', at_most=1)
    self.expect_pass(post_process.MustRunRE, 'a', at_least=1, at_most=1)

  def test_mr_fail_re(self):
    self.expect_fails(1, post_process.MustRunRE, 'x')
    self.expect_fails(1, post_process.MustRunRE, 'b', at_most=1)
    self.expect_fails(1, post_process.MustRunRE, 'b', at_least=4)

  def test_dnr_pass(self):
    self.expect_pass(post_process.DoesNotRun, 'x')

  def test_dnr_fail(self):
    self.expect_fails(1, post_process.DoesNotRun, 'a')

  def test_dnr_pass_re(self):
    self.expect_pass(post_process.DoesNotRunRE, 'x')

  def test_dnr_fail_re(self):
    self.expect_fails(3, post_process.DoesNotRunRE, 'b')


class TestStepStatus(PostProcessUnitTest):
  """Test case for checks relating to step status."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return collections.OrderedDict([
        ('success-step', {
            'name': 'success-step',
            'status': 'SUCCESS'
        }),
        ('failure-step', {
            'name': 'failure-step',
            'status': 'FAILURE'
        }),
        ('exception-step', {
            'name': 'exception-step',
            'status': 'EXCEPTION'
        }),
    ])

  def test_step_success_pass(self):
    self.expect_pass(post_process.StepSuccess, 'success-step')

  def test_step_success_fail(self):
    failures = self.expect_fails(1, post_process.StepSuccess, 'failure-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'SUCCESS'))")
    failures = self.expect_fails(1, post_process.StepSuccess, 'exception-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'SUCCESS'))")

  def test_step_failure_pass(self):
    self.expect_pass(post_process.StepFailure, 'failure-step')

  def test_step_failure_fail(self):
    failures = self.expect_fails(1, post_process.StepFailure, 'success-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'FAILURE'))")
    failures = self.expect_fails(1, post_process.StepFailure, 'exception-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'FAILURE'))")

  def test_step_exception_pass(self):
    self.expect_pass(post_process.StepException, 'exception-step')

  def test_step_exception_fail(self):
    failures = self.expect_fails(1, post_process.StepException, 'success-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'EXCEPTION'))")
    failures = self.expect_fails(1, post_process.StepException, 'failure-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'EXCEPTION'))")


class TestStepCommandEquals(PostProcessUnitTest):
  """Test case for StepCommandEquals."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return make_step_dict('my-step')

  def test_pass(self):
    """Assert that comparing against the exact cmd list passes."""
    self.expect_pass(post_process.StepCommandEquals, 'my-step',
                     ['thing', 'other'])

  def test_too_many_args(self):
    """Assert that comparing against the cmd list plus extra args fails."""
    self.expect_fails(1, post_process.StepCommandEquals, 'my-step',
                      ['thing', 'other', 'foo'])

  def test_too_few_args(self):
    """Assert that comparing against the cmd list minus some args fails."""
    self.expect_fails(1, post_process.StepCommandEquals, 'my-step', ['thing'])

  def test_string_instead_of_list(self):
    """Assert that comparing against a command string fails."""
    self.expect_fails(1, post_process.StepCommandEquals, 'my-step',
                      'thing other')

  def test_regex_would_pass(self):
    """Assert that comparing against a list of cmd regexes fails."""
    self.expect_pass(post_process.StepCommandRE, 'my-step',
                     ['thing', '[other]+'])
    self.expect_fails(1, post_process.StepCommandEquals, 'my-step',
                      ['thing', '[other]+'])


class TestStepCommandRe(PostProcessUnitTest):
  """Test case for StepCommandRE."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a stadnard step dict for this test case."""
    return collections.OrderedDict([('x', {
        'name': 'x',
        'cmd': ['echo', 'foo', 'bar', 'baz']
    })])

  def test_step_command_re_pass(self):
    self.expect_pass(post_process.StepCommandRE, 'x',
                     ['echo', 'f.*', 'bar', '.*z'])

  def test_step_command_re_fail(self):
    failures = self.expect_fails(2, post_process.StepCommandRE, 'x',
                                 ['echo', 'fo', 'bar2', 'baz'])
    self.assertHas(failures[0],
                   'check(_fullmatch(expected, actual))',
                   "expected: 'fo'")
    self.assertHas(failures[1],
                   'check(_fullmatch(expected, actual))',
                   "expected: 'bar2'")

    failures = self.expect_fails(1, post_process.StepCommandRE, 'x',
                                 ['echo', 'foo'])
    self.assertHas(failures[0],
                   "CHECK 'all arguments matched'",
                   "unmatched: ['bar', 'baz']")

    failures = self.expect_fails(1, post_process.StepCommandRE, 'x',
                                 ['echo', 'foo', 'bar', 'baz', 'quux', 'quuy'])
    self.assertHas(failures[0],
                   "CHECK 'all patterns used'",
                   "unused: ['quux', 'quuy']")


class TestStepCommandContains(PostProcessUnitTest):
  """Test case for StepCommandContains."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return collections.OrderedDict([('two', {
        'name': 'two',
        'cmd': ['a', 'b']
    }), ('one', {
        'name': 'one',
        'cmd': ['a']
    }), ('zero', {
        'name': 'zero',
        'cmd': []
    }), ('x', {
        'name': 'x',
        'cmd': ['echo', 'foo', 'bar', 'baz']
    })])

  def expect_fail(self, func, failure, *args, **kwargs):
    _, failures = self.post_process(func, *args, **kwargs)
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[0], 'CHECK %r' % failure)
    return failures

  def test_step_command_contains_one_pass(self):
    self.expect_pass(post_process.StepCommandContains, 'one', ['a'])

  def test_step_command_contains_one_pass_trivial(self):
    self.expect_pass(post_process.StepCommandContains, 'one', [])

  def test_step_command_contains_one_fail(self):
    self.expect_fail(post_process.StepCommandContains,
                     "command line for step one contained ['b']",
                     'one', ['b'])

  def test_step_command_contains_two_fail_order(self):
    self.expect_fail(post_process.StepCommandContains,
                     "command line for step two contained ['b', 'a']",
                     'two', ['b', 'a'])

  def test_step_command_contains_zero_pass(self):
    self.expect_pass(post_process.StepCommandContains, 'zero', [])

  def test_step_command_contains_zero_fail(self):
    self.expect_fail(post_process.StepCommandContains,
                     "command line for step zero contained ['a']",
                     'zero', ['a'])

  def test_step_command_contains_pass(self):
    self.expect_pass(post_process.StepCommandContains, 'x',
                     ['echo', 'foo', 'bar'])
    self.expect_pass(post_process.StepCommandContains, 'x',
                     ['foo', 'bar', 'baz'])

  def test_step_command_contains_fail(self):
    self.expect_fail(post_process.StepCommandContains,
                     'command line for step x contained %r' % ['foo', 'baz'],
                     'x', ['foo', 'baz'])


class TestStepCommandDoesNotContain(PostProcessUnitTest):
  """Test case for StepCommandDoesNotContain."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return collections.OrderedDict([('two', {
        'name': 'two',
        'cmd': ['a', 'b']
    }), ('one', {
        'name': 'one',
        'cmd': ['a']
    }), ('zero', {
        'name': 'zero',
        'cmd': []
    }), ('x', {
        'name': 'x',
        'cmd': ['echo', 'foo', 'bar', 'baz']
    })])

  def expect_pass(self, func, *args, **kwargs):
    _, failures = self.post_process(func, *args, **kwargs)
    self.assertEqual(len(failures), 0)

  def expect_fail(self, func, *args, **kwargs):
    _, failures = self.post_process(func, *args, **kwargs)
    self.assertEqual(len(failures), 1)
    return failures

  def test_step_command_does_not_contain_one_pass(self):
    self.expect_pass(post_process.StepCommandDoesNotContain, 'one', ['foo'])

  def test_step_command_does_not_contain_one_fail(self):
    self.expect_fail(post_process.StepCommandDoesNotContain, 'one', ['a'])

  def test_step_command_does_not_contain_two_pass_order(self):
    self.expect_pass(post_process.StepCommandDoesNotContain, 'two', ['b', 'a'])

  def test_step_command_does_not_contain_two_fail_order(self):
    self.expect_fail(post_process.StepCommandDoesNotContain, 'two', ['a', 'b'])

  def test_step_command_does_not_contain_fail(self):
    self.expect_fail(post_process.StepCommandDoesNotContain, 'x',
                     ['echo', 'foo', 'bar'])
    self.expect_fail(post_process.StepCommandDoesNotContain, 'x',
                     ['foo', 'bar', 'baz'])

  def test_step_command_does_not_contain_pass(self):
    self.expect_pass(post_process.StepCommandDoesNotContain, 'x',
                     ['foo', 'baz'])


class TestStepText(PostProcessUnitTest):
  """Test case for checks that relate to step text and step summary."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return collections.OrderedDict([('x', {
        'name': 'x',
        'step_text': 'foobar',
        'step_summary_text': 'test summary',
    })])

  def test_step_text_equals_pass(self):
    self.expect_pass(post_process.StepTextEquals, 'x', 'foobar')

  def test_step_text_equals_fail(self):
    failures = self.expect_fails(1, post_process.StepTextEquals, 'x', 'foo')
    self.assertHas(failures[0],
                   'check((step_odict[step].step_text == expected))')

  def test_step_text_contains_pass(self):
    self.expect_pass(post_process.StepTextContains, 'x', ['foo', 'bar'])

  def test_step_summary_text_equals_pass(self):
    self.expect_pass(post_process.StepSummaryEquals, 'x', 'test summary')

  def test_step_summary_text_equals_fail(self):
    failures = self.expect_fails(1, post_process.StepSummaryEquals, 'x',
                                 'bad')
    self.assertHas(failures[0],
                   'check((step_odict[step].step_summary_text == expected))',
                   "expected: 'bad'")


  def test_step_text_contains_fail(self):
    failures = self.expect_fails(
        2, post_process.StepTextContains, 'x', ['food', 'bar', 'baz'])
    self.assertHas(failures[0],
                   'check((expected in step_odict[step].step_text))',
                   "expected: 'food'")
    self.assertHas(failures[1],
                   'check((expected in step_odict[step].step_text))',
                   "expected: 'baz'")


class TestLog(PostProcessUnitTest):
  """Test case for checks that relate to logs."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return collections.OrderedDict([('x', {
        'name': 'x',
        'logs': {
            'log-x': 'foo\nbar',
        },
    })])

  def test_has_log_pass(self):
    self.expect_pass(post_process.HasLog, 'x', 'log-x')

  def test_has_log_fail(self):
    failures = self.expect_fails(1, post_process.HasLog, 'x', 'log-y')
    self.assertHas(failures[0], 'check((log in step_odict[step].logs))')

  def test_does_not_have_log_pass(self):
    self.expect_pass(post_process.DoesNotHaveLog, 'x', 'log-y')

  def test_does_not_have_log_fail(self):
    failures = self.expect_fails(1, post_process.DoesNotHaveLog, 'x', 'log-x')
    self.assertHas(failures[0], 'check((log not in step_odict[step].logs))')

  def test_log_equals_pass(self):
    self.expect_pass(post_process.LogEquals, 'x', 'log-x', 'foo\nbar')

  def test_log_equals_fail(self):
    failures = self.expect_fails(1, post_process.LogEquals,
                                 'x', 'log-x', 'foo\nbar\n')
    self.assertHas(failures[0],
                   'check((step_odict[step].logs[log] == expected))')

  def test_log_contains_pass(self):
    self.expect_pass(post_process.LogContains, 'x', 'log-x',
                     ['foo\n', '\nbar', 'foo\nbar'])

  def test_log_contains_fail(self):
    failures = self.expect_fails(
        3, post_process.LogContains, 'x', 'log-x',
        ['food', 'bar', 'baz', 'foobar'])
    self.assertHas(failures[0],
                   'check((expected in step_odict[step].logs[log]))',
                   "expected: 'food'")
    self.assertHas(failures[1],
                   'check((expected in step_odict[step].logs[log]))',
                   "expected: 'baz'")
    self.assertHas(failures[2],
                   'check((expected in step_odict[step].logs[log]))',
                   "expected: 'foobar'")

  def test_log_does_not_contain_pass(self):
    self.expect_pass(post_process.LogDoesNotContain, 'x', 'log-x',
                     ['i dont exist'])

  def test_log_does_not_contain_fail(self):
    failures = self.expect_fails(1, post_process.LogDoesNotContain, 'x',
                                 'log-x', ['foo'])
    self.assertHas(failures[0],
                   'check((unexpected not in step_odict[step].logs[log]))',
                   "unexpected: 'foo'")


class TestProperty(PostProcessUnitTest):
  """Test case for checks that relate to output properties."""

  @property
  def step_dict(self) -> dict[str, dict[str, Any]]:
    """Return a standard step dict for this test case."""
    return collections.OrderedDict([('step', {
        'name': 'step',
        'output_properties': {'x': 'foo', 'y': list('bar')}
    })])

  def test_property_equals_pass(self):
    self.expect_pass(post_process.PropertyEquals, 'x', 'foo')

  def test_property_equals_fail(self):
    failures = self.expect_fails(1, post_process.PropertyEquals, 'x', 'foobar')
    self.assertHas(failures[0], 'check((build_properties[key] == value))')

  def test_property_matches_regex_pass(self):
    self.expect_pass(post_process.PropertyMatchesRE, 'x', r'^fo+$')

  def test_property_matches_regex_not_str(self):
    failures = self.expect_fails(1, post_process.PropertyMatchesRE, 'y',
                                 r'^fo+$')
    self.assertHas(failures[0], 'check(isinstance(build_properties[key], str))')

  def test_property_matches_regex_fail(self):
    failures = self.expect_fails(1, post_process.PropertyMatchesRE, 'x',
                                 r'^fooo+$')
    self.assertHas(failures[0],
                   'check(re.search(pattern, build_properties[key]))')

  def test_property_matches_callable_pass(self):
    self.expect_pass(post_process.PropertyMatchesCallable, 'y',
                     lambda i: ''.join(i) == 'bar')

  def test_property_matches_callable_fail(self):
    failures = self.expect_fails(1, post_process.PropertyMatchesCallable, 'y',
                                 lambda i: ''.join(i) == 'foo')
    self.assertHas(failures[0], 'check(matcher(build_properties[key]))')

  def test_properties_contain_pass(self):
    self.expect_pass(post_process.PropertiesContain, 'x')

  def test_properties_contain_fail(self):
    failures = self.expect_fails(1, post_process.PropertiesContain, 'q')
    self.assertHas(failures[0], 'check((key in build_properties))')

  def test_properties_do_not_contain_pass(self):
    self.expect_pass(post_process.PropertiesDoNotContain, 'q')

  def test_properties_do_not_contain_fail(self):
    failures = self.expect_fails(1, post_process.PropertiesDoNotContain, 'x')
    self.assertHas(failures[0], 'check((key not in build_properties))')


if __name__ == '__main__':
  test_env.main()
