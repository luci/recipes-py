#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.utils import iteritems

from collections import OrderedDict

import test_env

from recipe_engine import post_process
from recipe_engine.internal.test import magic_check_fn
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.recipe_engine.internal.test.runner import Outcome


def mkS(name, *fields):
  ret = {
    'name': name,
    'cmd': ['thing', 'other'],
    'cwd': 'some-directory',
    'env': {'var': 'value'},
  }
  if fields:
    return {k: v for k, v in iteritems(ret) if k in fields or k == 'name'}
  return ret


def mkD(*steps):
  return OrderedDict([(n, mkS(n)) for n in steps])


class PostProcessUnitTest(test_env.RecipeEngineUnitTest):
  @staticmethod
  def post_process(d, f, *args, **kwargs):
    test_data = RecipeTestApi().post_process(f, *args, **kwargs)
    results = Outcome.Results()
    expectations = magic_check_fn.post_process(results, d, test_data)
    return expectations, results.check

  def assertHas(self, failure, *text):
    combined = '\n'.join(failure.lines)
    for item in text:
      self.assertIn(item, combined)


class TestFilter(PostProcessUnitTest):
  def setUp(self):
    super(TestFilter, self).setUp()
    self.d = mkD('a', 'b', 'b.sub', 'b.sub2')
    self.f = post_process.Filter

  def test_basic(self):
    results, failures = self.post_process(self.d, self.f('a', 'b'))
    self.assertEqual(results, mkD('a', 'b').values())
    self.assertEqual(len(failures), 0)

  def test_built(self):
    f = self.f()
    f = f.include('b')
    f = f.include('a')
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('a', 'b').values())
    self.assertEqual(len(failures), 0)

  def test_built_fields(self):
    f = self.f()
    f = f.include('b', ['env'])
    f = f.include('a', ['cmd'])
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, [mkS('a', 'cmd'), mkS('b', 'env')])
    self.assertEqual(len(failures), 0)

  def test_built_extra_includes(self):
    f = self.f('a', 'b', 'x')
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('a', 'b').values())
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[0],
                   'check((len(unused_includes) == 0))',
                   "unused_includes: {'x': ()}")

  def test_re(self):
    f = self.f().include_re(r'b\.')
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('b.sub', 'b.sub2').values())
    self.assertEqual(len(failures), 0)

  def test_re_low_limit(self):
    f = self.f().include_re(r'b\.', at_least=3)
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('b.sub', 'b.sub2').values())
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[-1],
                   'check((re_usage_count[regex] >= at_least))',
                   'at_least: 3',
                   're_usage_count[regex]: 2',
                   'regex: re.compile(\'b\\\\.\')')

  def test_re_high_limit(self):
    f = self.f().include_re(r'b\.', at_most=1)
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('b.sub', 'b.sub2').values())
    self.assertEqual(len(failures), 1)
    self.assertHas(failures[0], 'check((re_usage_count[regex] <= at_most))')
    self.assertHas(failures[0],
                   'at_most: 1',
                   're_usage_count[regex]: 2',
                   'regex: re.compile(\'b\\\\.\')')


class TestRun(PostProcessUnitTest):
  def setUp(self):
    super(TestRun, self).setUp()
    self.d = mkD('a', 'b', 'b.sub', 'b.sub2')

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)

  def test_mr_pass(self):
    self.expect_fails(0, post_process.MustRun, 'a')

  def test_mr_fail(self):
    self.expect_fails(1, post_process.MustRun, 'x')

  def test_mr_pass_re(self):
    self.expect_fails(0, post_process.MustRunRE, 'a')
    self.expect_fails(0, post_process.MustRunRE, 'a', at_most=1)
    self.expect_fails(0, post_process.MustRunRE, 'a', at_least=1, at_most=1)

  def test_mr_fail_re(self):
    self.expect_fails(1, post_process.MustRunRE, 'x')
    self.expect_fails(1, post_process.MustRunRE, 'b', at_most=1)
    self.expect_fails(1, post_process.MustRunRE, 'b', at_least=4)

  def test_dnr_pass(self):
    self.expect_fails(0, post_process.DoesNotRun, 'x')

  def test_dnr_fail(self):
    self.expect_fails(1, post_process.DoesNotRun, 'a')

  def test_dnr_pass_re(self):
    self.expect_fails(0, post_process.DoesNotRunRE, 'x')

  def test_dnr_fail_re(self):
    self.expect_fails(3, post_process.DoesNotRunRE, 'b')


class TestStepStatus(PostProcessUnitTest):
  def setUp(self):
    super(TestStepStatus, self).setUp()
    self.d = OrderedDict([
        ('success-step', {'name': 'success-step', 'status': 'SUCCESS'}),
        ('failure-step', {'name': 'failure-step', 'status': 'FAILURE'}),
        ('exception-step', {'name': 'exception-step', 'status': 'EXCEPTION'}),
    ])

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def test_step_success_pass(self):
    self.expect_fails(0, post_process.StepSuccess, 'success-step')

  def test_step_success_fail(self):
    failures = self.expect_fails(1, post_process.StepSuccess, 'failure-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'SUCCESS'))")
    failures = self.expect_fails(1, post_process.StepSuccess, 'exception-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'SUCCESS'))")

  def test_step_failure_pass(self):
    self.expect_fails(0, post_process.StepFailure, 'failure-step')

  def test_step_failure_fail(self):
    failures = self.expect_fails(1, post_process.StepFailure, 'success-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'FAILURE'))")
    failures = self.expect_fails(1, post_process.StepFailure, 'exception-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'FAILURE'))")

  def test_step_exception_pass(self):
    self.expect_fails(0, post_process.StepException, 'exception-step')

  def test_step_exception_fail(self):
    failures = self.expect_fails(1, post_process.StepException, 'success-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'EXCEPTION'))")
    failures = self.expect_fails(1, post_process.StepException, 'failure-step')
    self.assertHas(failures[0],
                   "check((step_odict[step].status == 'EXCEPTION'))")


class TestStepCommandRe(PostProcessUnitTest):
  def setUp(self):
    super(TestStepCommandRe, self).setUp()
    self.d = OrderedDict([
        ('x', {'name': 'x', 'cmd': ['echo', 'foo', 'bar', 'baz']})
    ])

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def test_step_command_re_pass(self):
    self.expect_fails(0, post_process.StepCommandRE, 'x',
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
  def setUp(self):
    super(TestStepCommandContains, self).setUp()
    self.d = OrderedDict([
        ('two', {'name': 'two', 'cmd': ['a', 'b']}),
        ('one', {'name': 'one', 'cmd': ['a']}),
        ('zero', {'name': 'zero', 'cmd': []}),
        ('x', {'name': 'x', 'cmd': ['echo', 'foo', 'bar', 'baz']})
    ])

  def expect_pass(self, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), 0)

  def expect_fail(self, func, failure, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
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

  def setUp(self):
    super(TestStepCommandDoesNotContain, self).setUp()
    self.d = OrderedDict([('two', {
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
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), 0)

  def expect_fail(self, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
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
  def setUp(self):
    super(TestStepText, self).setUp()
    self.d = OrderedDict([
        ('x', {
            'name': 'x',
            'step_text': 'foobar',
            'step_summary_text' : 'test summary',
        })
    ])

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def test_step_text_equals_pass(self):
    self.expect_fails(0, post_process.StepTextEquals, 'x', 'foobar')

  def test_step_text_equals_fail(self):
    failures = self.expect_fails(1, post_process.StepTextEquals, 'x', 'foo')
    self.assertHas(failures[0],
                   'check((step_odict[step].step_text == expected))')

  def test_step_text_contains_pass(self):
    self.expect_fails(0, post_process.StepTextContains, 'x', ['foo', 'bar'])

  def test_step_summary_text_equals_pass(self):
    self.expect_fails(0, post_process.StepSummaryEquals, 'x', 'test summary')

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
  def setUp(self):
    super(TestLog, self).setUp()
    self.d = OrderedDict([
        ('x', {
            'name': 'x',
            'logs': {
                'log-x': 'foo\nbar',
            },
        })
    ])

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def test_log_equals_pass(self):
    self.expect_fails(0, post_process.LogEquals, 'x', 'log-x', 'foo\nbar')

  def test_log_equals_fail(self):
    failures = self.expect_fails(1, post_process.LogEquals,
                                 'x', 'log-x', 'foo\nbar\n')
    self.assertHas(failures[0],
                   'check((step_odict[step].logs[log] == expected))')

  def test_log_contains_pass(self):
    self.expect_fails(0, post_process.LogContains, 'x', 'log-x',
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


if __name__ == '__main__':
  test_env.main()
