#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from collections import OrderedDict

import test_env

from recipe_engine import post_process
from recipe_engine.internal.test import magic_check_fn
from recipe_engine.recipe_test_api import RecipeTestApi


def mkS(name, *fields):
  ret = {
    'name': name,
    'sub_a': ['thing', 'other'],
    'sub_b': 100,
    'sub_c': 'hi',
  }
  if fields:
    return {k: v for k, v in ret.iteritems() if k in fields or k == 'name'}
  return ret


def mkD(*steps):
  return OrderedDict([(n, mkS(n)) for n in steps])


class PostProcessUnitTest(test_env.RecipeEngineUnitTest):
  @staticmethod
  def post_process(d, f, *args, **kwargs):
    test_data = RecipeTestApi().post_process(f, *args, **kwargs)
    return magic_check_fn.post_process(d, test_data)


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
    f = f.include('b', ['sub_b'])
    f = f.include('a', ['sub_a'])
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, [mkS('a', 'sub_a'), mkS('b', 'sub_b')])
    self.assertEqual(len(failures), 0)

  def test_built_extra_includes(self):
    f = self.f('a', 'b', 'x')
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('a', 'b').values())
    self.assertEqual(len(failures), 1)
    self.assertEqual(failures[0].frames[-1].code,
                     'check((len(unused_includes) == 0))')
    self.assertEqual(failures[0].frames[-1].varmap,
                     {'unused_includes': "{'x': ()}"})

  def test_re(self):
    f = self.f().include_re('b\.')
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('b.sub', 'b.sub2').values())
    self.assertEqual(len(failures), 0)

  def test_re_low_limit(self):
    f = self.f().include_re('b\.', at_least=3)
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('b.sub', 'b.sub2').values())
    self.assertEqual(len(failures), 1)
    self.assertEqual(failures[0].frames[-1].code,
                     'check((re_usage_count[regex] >= at_least))')
    self.assertEqual(failures[0].frames[-1].varmap,
                     {'at_least': '3',
                      're_usage_count[regex]': '2',
                      'regex': "re.compile('b\\\\.')"})

  def test_re_high_limit(self):
    f = self.f().include_re('b\.', at_most=1)
    results, failures = self.post_process(self.d, f)
    self.assertEqual(results, mkD('b.sub', 'b.sub2').values())
    self.assertEqual(len(failures), 1)
    self.assertEqual(failures[0].frames[-1].code,
                     'check((re_usage_count[regex] <= at_most))')
    self.assertEqual(failures[0].frames[-1].varmap,
                     {'at_most': '1',
                      're_usage_count[regex]': '2',
                      'regex': "re.compile('b\\\\.')"})


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
        ('success-step', {'~followup_annotations': []}),
        ('failure-step', {'~followup_annotations': ['@@@STEP_FAILURE@@@']}),
        ('exception-step', {'~followup_annotations': ['@@@STEP_EXCEPTION@@@']}),
    ])

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def test_step_success_pass(self):
    self.expect_fails(0, post_process.StepSuccess, 'success-step')

  def test_step_success_fail(self):
    failures = self.expect_fails(1, post_process.StepSuccess, 'failure-step')
    self.assertEqual(failures[0].name, 'step failure-step was success')
    failures = self.expect_fails(1, post_process.StepSuccess, 'exception-step')
    self.assertEqual(failures[0].name, 'step exception-step was success')

  def test_step_failure_pass(self):
    self.expect_fails(0, post_process.StepFailure, 'failure-step')

  def test_step_failure_fail(self):
    failures = self.expect_fails(1, post_process.StepFailure, 'success-step')
    self.assertEqual(failures[0].name, 'step success-step was failure')
    failures = self.expect_fails(1, post_process.StepFailure, 'exception-step')
    self.assertEqual(failures[0].name, 'step exception-step was failure')

  def test_step_exception_pass(self):
    self.expect_fails(0, post_process.StepException, 'exception-step')

  def test_step_exception_fail(self):
    failures = self.expect_fails(1, post_process.StepException, 'success-step')
    self.assertEqual(failures[0].name, 'step success-step was exception')
    failures = self.expect_fails(1, post_process.StepException, 'failure-step')
    self.assertEqual(failures[0].name, 'step failure-step was exception')


class TestStepCommandRe(PostProcessUnitTest):
  def setUp(self):
    super(TestStepCommandRe, self).setUp()
    self.d = OrderedDict([
        ('x', {'cmd': ['echo', 'foo', 'bar', 'baz']})
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
    self.assertEqual(failures[0].frames[-1].code,
                     'check(_fullmatch(expected, actual))')
    self.assertEqual(failures[0].frames[-1].varmap['expected'],
                      "'fo'")
    self.assertEqual(failures[1].frames[-1].code,
                     'check(_fullmatch(expected, actual))')
    self.assertEqual(failures[1].frames[-1].varmap['expected'],
                      "'bar2'")

    failures = self.expect_fails(1, post_process.StepCommandRE, 'x',
                                 ['echo', 'foo'])
    self.assertEqual(failures[0].name, 'all arguments matched')
    self.assertEqual(failures[0].frames[-1].varmap['unmatched'],
                      "['bar', 'baz']")

    failures = self.expect_fails(1, post_process.StepCommandRE, 'x',
                                 ['echo', 'foo', 'bar', 'baz', 'quux', 'quuy'])
    self.assertEqual(failures[0].name, 'all patterns used')
    self.assertEqual(failures[0].frames[-1].varmap['unused'],
                     "['quux', 'quuy']")


class TestStepCommandContains(PostProcessUnitTest):
  def setUp(self):
    super(TestStepCommandContains, self).setUp()
    self.d = OrderedDict([
        ('two', {'cmd': ['a', 'b']}),
        ('one', {'cmd': ['a']}),
        ('zero', {'cmd': []}),
        ('no_cmd', {}),
        ('x', {'cmd': ['echo', 'foo', 'bar', 'baz']})
    ])

  def expect_pass(self, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), 0)

  def expect_fail(self, func, failure, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), 1)
    self.assertEqual(failures[0].name, failure)
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

  def test_step_command_contains_no_cmd_fail(self):
    self.expect_fail(post_process.StepCommandContains,
                     'step no_cmd had a command',
                     'no_cmd', [])

  def test_step_command_contains_pass(self):
    self.expect_pass(post_process.StepCommandContains, 'x',
                     ['echo', 'foo', 'bar'])
    self.expect_pass(post_process.StepCommandContains, 'x',
                     ['foo', 'bar', 'baz'])

  def test_step_command_contains_fail(self):
    self.expect_fail(post_process.StepCommandContains,
                     'command line for step x contained %r' % ['foo', 'baz'],
                     'x', ['foo', 'baz'])


class TestStepText(PostProcessUnitTest):
  def setUp(self):
    super(TestStepText, self).setUp()
    self.d = OrderedDict([
        ('x', {
            '~followup_annotations': ['@@@STEP_TEXT@foobar@@@'],
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
    self.assertEqual(failures[0].frames[-1].code,
                     'check((actual == expected))')

  def test_step_text_contains_pass(self):
    self.expect_fails(0, post_process.StepTextContains, 'x', ['foo', 'bar'])

  def test_step_text_contains_fail(self):
    failures = self.expect_fails(
        2, post_process.StepTextContains, 'x', ['food', 'bar', 'baz'])
    self.assertEquals(failures[0].frames[-1].code,
                      'check((expected in actual))')
    self.assertEquals(failures[0].frames[-1].varmap['expected'],
                      "'food'")
    self.assertEquals(failures[1].frames[-1].code,
                      'check((expected in actual))')
    self.assertEquals(failures[1].frames[-1].varmap['expected'],
                      "'baz'")


class TestLog(PostProcessUnitTest):
  def setUp(self):
    super(TestLog, self).setUp()
    self.d = OrderedDict([
        ('x', {
            '~followup_annotations': [
                '@@@STEP_LOG_LINE@log-x@foo@@@',
                '@@@STEP_LOG_LINE@log-x@bar@@@',
                '@@@STEP_LOG_END@log-x@@@',
            ],
        })
    ])

  def expect_fails(self, num_fails, func, *args, **kwargs):
    _, failures = self.post_process(self.d, func, *args, **kwargs)
    self.assertEqual(len(failures), num_fails)
    return failures

  def test_log_equals_pass(self):
    self.expect_fails(0, post_process.LogEquals, 'x', 'log-x', 'foo\nbar\n')

  def test_log_equals_fail(self):
    failures = self.expect_fails(1, post_process.LogEquals,
                                 'x', 'log-y', 'foo\nbar\n')
    self.assertEqual(failures[0].name, 'step x has log log-y')

    failures = self.expect_fails(1, post_process.LogEquals,
                                 'x', 'log-x', 'foo\nbar')
    self.assertEqual(failures[0].frames[-1].code,
                     'check((actual == expected))')

  def test_log_contains_pass(self):
    self.expect_fails(0, post_process.LogContains, 'x', 'log-x',
                      ['foo\n', 'bar\n', 'foo\nbar'])

  def test_log_contains_fail(self):
    failures = self.expect_fails(1, post_process.LogContains, 'x', 'log-y',
                          ['foo', 'bar'])
    self.assertEqual(failures[0].name, 'step x has log log-y')

    failures = self.expect_fails(
        3, post_process.LogContains, 'x', 'log-x',
        ['food', 'bar', 'baz', 'foobar'])
    self.assertEquals(failures[0].frames[-1].code,
                      'check((expected in actual))')
    self.assertEquals(failures[0].frames[-1].varmap['expected'],
                      "'food'")
    self.assertEquals(failures[1].frames[-1].code,
                      'check((expected in actual))')
    self.assertEquals(failures[1].frames[-1].varmap['expected'],
                      "'baz'")
    self.assertEquals(failures[2].frames[-1].code,
                      'check((expected in actual))')
    self.assertEquals(failures[2].frames[-1].varmap['expected'],
                      "'foobar'")


if __name__ == '__main__':
  test_env.main()
