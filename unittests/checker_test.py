#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys
import copy

from collections import OrderedDict

import test_env

from recipe_engine.recipe_test_api import PostprocessHookContext, RecipeTestApi
from recipe_engine.internal.test.magic_check_fn import \
  Checker, CheckException, CheckFrame, PostProcessError, StepsDict, \
  VerifySubset, post_process


HOOK_CONTEXT = PostprocessHookContext(lambda: None, (), {}, '<filename>', 0)


class TestChecker(test_env.RecipeEngineUnitTest):
  def sanitize(self, checkframe):
    return checkframe._replace(line=0, fname='')

  def mk(self, fname, code, varmap):
    return CheckFrame(
      fname='', line=0, function=fname, code=code, varmap=varmap)

  def test_no_calls(self):
    c = Checker(HOOK_CONTEXT)
    def body(_):
      pass
    body(c)
    self.assertEqual(len(c.failed_checks), 0)

  def test_success_call(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      check(True is True)
    body(c)
    self.assertEqual(len(c.failed_checks), 0)

  def test_simple_fail(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      check(True is False)
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', 'check((True is False))', {}))

  def test_simple_fail_multiline(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      falsey = lambda: False
      check(
        True is

        falsey()
      )
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', 'check((True is falsey()))', {}))

  def test_simple_fail_multiline_multistatement(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      other = 'thing'
      falsey = lambda: False
      check(
        True is

        falsey()); other  # pylint: disable=pointless-statement
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', 'check((True is falsey())); other', {
        'other': "'thing'" }))

  def test_fail_nested_statement(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      other = 'thing'
      falsey = lambda: False
      if True:
        while True:
          try:
            check(
              True is

              falsey()); other  # pylint: disable=pointless-statement
            break
          except Exception:
            pass
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', 'check((True is falsey())); other', {
        'other': "'thing'" }))

  def test_var_fail(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      val = True
      check(val is False)
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', 'check((val is False))', {'val': 'True'}))

  def test_dict_membership(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      targ = {'a': 'b', 'c': 'd'}
      check('a' not in targ)
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', "check(('a' not in targ))",
              {'targ.keys()': "['a', 'c']"}))

  def test_dict_lookup(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      targ = {'a': {'sub': 'b'}, 'c': 'd'}
      check('cow' in targ['a'])
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', "check(('cow' in targ['a']))",
              {"targ['a'].keys()": "['sub']"}))

  def test_dict_lookup_nest(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      sub = 'sub'
      targ = {'a': {'sub': 'whee'}, 'c': 'd'}
      check('me' == targ['a'][sub])
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', "check(('me' == targ['a'][sub]))",
              {"targ['a'][sub]": "'whee'", 'sub': "'sub'"}))

  def test_lambda_call(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      vals = ['whee', 'sub']
      targ = {'a': {'sub': 'whee'}, 'c': 'd'}
      map(lambda v: check(v in targ['a']), vals)
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 2)
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[0]),
      self.mk('body', "map((lambda v: check((v in targ['a']))), vals)", None))
    self.assertEqual(
      self.sanitize(c.failed_checks[0].frames[1]),
      self.mk('<lambda>', "map((lambda v: check((v in targ['a']))), vals)",
              {"targ['a'].keys()": "['sub']", 'v': "'whee'"}))

  def test_lambda_in_multiline_expr_call(self):
    c = Checker(HOOK_CONTEXT)
    def wrap(f):
      return f
    def body(check, f):
      f(check)
    value = 'food'
    target = ['foo', 'bar', 'baz']
    # Make sure the lambda is part of a larger expression that ends on a
    # later line than the lambda
    func = [lambda check: check(value == target),
            lambda check: check(value in target),
            lambda check: check(value and target),
           ][1]
    body(c, func)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 2)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('body', 'f(check)', None))
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[1]),
        self.mk('<lambda>', '(lambda check: check((value in target)))',
                {'value': "'food'", 'target': "['foo', 'bar', 'baz']"}))

  def test_if_test(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      vals = ['foo', 'bar']
      target = 'baz'
      if check(target in vals):
        pass
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('body', 'check((target in vals))',
                {'target': "'baz'", 'vals': "['foo', 'bar']"}))

  def test_elif_test(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      vals = ['foo', 'bar']
      target = 'baz'
      if False:
        pass
      elif check(target in vals):
        pass
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('body', 'check((target in vals))',
                {'target': "'baz'", 'vals': "['foo', 'bar']"}))

  def test_while_test(self):
    c = Checker(HOOK_CONTEXT)
    def body(check):
      vals = ['foo', 'bar', 'baz']
      invalid_value = 'bar'
      i = 0
      while check(vals[i] != invalid_value):
        i += 1
    body(c)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('body', 'check((vals[i] != invalid_value))',
                {'i': '1', 'invalid_value': "'bar'", 'vals[i]': "'bar'"}))

  def test_steps_dict_implicit_check(self):
    d = OrderedDict(foo={})
    c = Checker(HOOK_CONTEXT)
    s = StepsDict(c, d)
    def body(check, steps_dict):
      check('x' in steps_dict['bar']['cmd'])
    with self.assertRaises(CheckException):
      body(c, s)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 2)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('body', "check(('x' in steps_dict['bar']['cmd']))", None))
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[1]),
        self.mk('__getitem__', 'step_present = check((step in steps_dict))',
                {'step': "'bar'", 'steps_dict.keys()': "['foo']"}))

  def test_steps_dict_implicit_check_no_checker_in_frame(self):
    d = OrderedDict(foo={})
    c = Checker(HOOK_CONTEXT)
    s = StepsDict(c, d)
    def body(check, steps_dict):
      # The failure backtrace for the implicit check should even includes frames
      # where check isn't explicitly passed
      def inner(steps_dict):
        return 'x' in steps_dict['bar']['cmd']
      check(inner(steps_dict))
    with self.assertRaises(CheckException):
      body(c, s)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 3)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('body', 'check(inner(steps_dict))', None))
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[1]),
        self.mk('inner', "return ('x' in steps_dict['bar']['cmd'])", None))
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[2]),
        self.mk('__getitem__', 'step_present = check((step in steps_dict))',
                {'step': "'bar'", 'steps_dict.keys()': "['foo']"}))

  def test_steps_dict_is_ignored(self):
    d = OrderedDict(foo={})
    c = Checker(HOOK_CONTEXT)
    s = StepsDict(c, d)
    body = lambda check, steps: check('bar' in steps)
    body(c, s)
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(len(c.failed_checks[0].frames), 1)
    self.assertEqual(
        self.sanitize(c.failed_checks[0].frames[0]),
        self.mk('<lambda>',
                "body = (lambda check, steps: check(('bar' in steps)))",
                {'steps.keys()': "['foo']"}))


class TestVerifySubset(test_env.RecipeEngineUnitTest):
  @staticmethod
  def mkData(*steps):
    return OrderedDict([
      (s, {
        'cmd': ['list', 'of', 'things'],
        'env': {
          'dict': 'of',
          'many': 'strings,'
        },
        'name': s,
        'status_code': 1,
      }) for s in steps
    ])

  def setUp(self):
    super(TestVerifySubset, self).setUp()
    self.v = VerifySubset
    self.d = self.mkData('a', 'b', 'c')
    self.c = copy.deepcopy(self.d)

  def test_types(self):
    self.assertIn(
      "type mismatch: 'str' v 'OrderedDict'",
      self.v('hi', self.d))

    self.assertIn(
      "type mismatch: 'list' v 'OrderedDict'",
      self.v(['hi'], self.d))

  def test_steps_dict(self):
    c = Checker(HOOK_CONTEXT)
    steps_dict = StepsDict(c, self.d)
    self.assertIsNone(self.v(self.d, steps_dict))
    self.assertIsNone(self.v(steps_dict, self.d))

  def test_empty(self):
    self.assertIsNone(self.v({}, self.d))
    self.assertIsNone(self.v(OrderedDict(), self.d))

  def test_empty_cmd(self):
    self.c['a']['cmd'] = []
    self.d['a']['cmd'] = []
    self.assertIsNone(self.v(self.c, self.d))

  def test_single_removal(self):
    del self.c['c']
    self.assertIsNone(self.v(self.c, self.d))

  def test_add(self):
    self.c['d'] = self.c['a']
    self.assertIn(
      "added key 'd'",
      self.v(self.c, self.d))

  def test_add_key(self):
    self.c['c']['blort'] = 'cake'
    self.assertIn(
      "added key 'blort'",
      self.v(self.c, self.d))

  def test_key_alter(self):
    self.c['c']['cmd'] = 'cake'
    self.assertEqual(
      "['c']['cmd']: type mismatch: 'str' v 'list'",
      self.v(self.c, self.d))

  def test_list_add(self):
    self.c['c']['cmd'].append('something')
    self.assertIn(
      "['c']['cmd']: too long: 4 v 3",
      self.v(self.c, self.d))

    self.c['c']['cmd'].pop(0)
    self.assertIn(
      "['c']['cmd']: added 1 elements",
      self.v(self.c, self.d))

  def test_list_of_dict(self):
    self.assertIsNone(
      self.v(
        [{'c': 'd', 'a': 'cat'}],
        [{'a': 'b'}, {'c': 'd'}]))

  def test_ordereddict(self):
    a = self.c['a']
    del self.c['a']
    self.c['a'] = a
    self.assertIn(
      "key 'a' is out of order",
      self.v(self.c, self.d))


class TestPostProcessHooks(test_env.RecipeEngineUnitTest):
  @staticmethod
  def mkApi():
    return RecipeTestApi()

  @staticmethod
  def mk(fname, code, varmap):
    return CheckFrame(
      fname='', line=0, function=fname, code=code, varmap=varmap)

  @staticmethod
  def sanitize(checkframe):
    return checkframe._replace(line=0, fname='')

  def assertCheckFailure(self, failure, func, args, kwargs):
    self.assertEqual(failure.ctx_func, func)
    self.assertEqual(failure.ctx_args, args)
    self.assertEqual(failure.ctx_kwargs, kwargs)

  def test_returning_none(self):
    d = OrderedDict([
        ('x', {'name': 'x', 'cmd': ['one', 'two', 'three']}),
        ('y', {'name': 'y', 'cmd': []}),
        ('z', {'name': 'z', 'cmd': ['foo', 'bar']}),
    ])
    test_data = self.mkApi().post_process(lambda check, steps: None)
    results, failures = post_process(d, test_data)
    self.assertEqual(results, [
        {'name': 'x', 'cmd': ['one', 'two', 'three']},
        {'name': 'y', 'cmd': []},
        {'name': 'z', 'cmd': ['foo', 'bar']},
    ])
    self.assertEqual(failures, [])

  def test_returning_subset(self):
    d = OrderedDict([
        ('x', {'name': 'x', 'cmd': ['one', 'two', 'three']}),
        ('y', {'name': 'y', 'cmd': []}),
        ('z', {'name': 'z', 'cmd': ['foo', 'bar']}),
    ])
    test_data = self.mkApi().post_process(
        lambda check, steps:
        OrderedDict((k, {'name': v['name']}) for k, v in steps.iteritems()))
    results, failures = post_process(d, test_data)
    self.assertEqual(results, [{'name': 'x'}, {'name': 'y'}, {'name': 'z'}])
    self.assertEqual(failures, [])

  def test_returning_empty(self):
    d = OrderedDict([
        ('x', {'name': 'x', 'cmd': ['one', 'two', 'three']}),
        ('y', {'name': 'y', 'cmd': []}),
        ('z', {'name': 'z', 'cmd': ['foo', 'bar']}),
    ])
    test_data = self.mkApi().post_process(lambda check, steps: {})
    results, failures = post_process(d, test_data)
    self.assertIsNone(results)
    self.assertEqual(failures, [])

  def test_returning_nonsubset(self):
    d = OrderedDict([
        ('x', {'name': 'x', 'cmd': ['one', 'two', 'three']}),
        ('y', {'name': 'y', 'cmd': []}),
        ('z', {'name': 'z', 'cmd': ['foo', 'bar']}),
    ])
    test_data = self.mkApi().post_process(
        lambda check, steps:
        OrderedDict((k, dict(cwd='cwd', **v)) for k, v in steps.iteritems()))
    with self.assertRaises(PostProcessError):
      post_process(d, test_data)

  def test_removing_name(self):
    d = OrderedDict([
        ('x', {'name': 'x', 'cmd': ['one', 'two', 'three']}),
        ('y', {'name': 'y', 'cmd': []}),
        ('z', {'name': 'z', 'cmd': ['foo', 'bar']}),
    ])
    test_data = self.mkApi().post_process(
        lambda check, steps:
        OrderedDict((k, {a: value for a, value in v.iteritems() if a != 'name'})
                    for k,v in steps.iteritems()))
    results, failures = post_process(d, test_data)
    self.assertEqual(results, [
        {'name': 'x', 'cmd': ['one', 'two', 'three']},
        {'name': 'y', 'cmd': []},
        {'name': 'z', 'cmd': ['foo', 'bar']},
    ])
    self.assertEqual(failures, [])

  def test_post_process_failure(self):
    d = OrderedDict([('x', {'name': 'x'})])
    def body(check, steps, *args, **kwargs):
      check('x' not in steps)
    test_data = self.mkApi().post_process(body, 'foo', 'bar', a=1, b=2)
    results, failures = post_process(d, test_data)
    self.assertEqual(results, [{'name': 'x'}])
    self.assertEqual(len(failures), 1)
    self.assertCheckFailure(failures[0],
                            'body', ["'foo'", "'bar'"], {'a': '1', 'b': '2'})
    self.assertEqual(len(failures[0].frames), 1)
    self.assertEqual(
        self.sanitize(failures[0].frames[0]),
        self.mk('body', "check(('x' not in steps))",
                {'steps.keys()': "['x']"}))

  def test_post_process_failure_in_multiple_hooks(self):
    d = OrderedDict([('x', {'name': 'x'})])
    def body(check, steps, *args, **kwargs):
      check('x' not in steps)
    def body2(check, steps, *args, **kwargs):
      check('y' in steps)
    api = self.mkApi()
    test_data = (api.post_process(body, 'foo', a=1) +
                 api.post_process(body2, 'bar', b=2))
    results, failures = post_process(d, test_data)
    self.assertEqual(results, [{'name': 'x'}])
    self.assertEqual(len(failures), 2)
    self.assertCheckFailure(failures[0], 'body', ["'foo'"], {'a': '1'})
    self.assertEqual(len(failures[0].frames), 1)
    self.assertEqual(
        self.sanitize(failures[0].frames[0]),
        self.mk('body', "check(('x' not in steps))",
                {'steps.keys()': "['x']"}))
    self.assertCheckFailure(failures[1], 'body2', ["'bar'"], {'b': '2'})
    self.assertEqual(len(failures[1].frames), 1)
    self.assertEqual(
        self.sanitize(failures[1].frames[0]),
        self.mk('body2', "check(('y' in steps))",
                {'steps.keys()': "['x']"}))

  def test_post_check_failure(self):
    d = OrderedDict([('x', {'name': 'x'})])
    test_data = self.mkApi().post_check(
        lambda check, steps, *args, **kwargs: check('x' not in steps),
        'foo', 'bar', a=1, b=2)
    results, failures = post_process(d, test_data)
    self.assertEqual(results, [{'name': 'x'}])
    self.assertEqual(len(failures), 1)
    self.assertCheckFailure(
        failures[0],
        "(lambda check, steps, *args, **kwargs: check(('x' not in steps)))",
        ["'foo'", "'bar'"], {'a': '1', 'b': '2'})
    self.assertEqual(len(failures[0].frames), 2)
    self.assertEqual(
        self.sanitize(failures[0].frames[0]),
        self.mk('post_check', 'f(check, steps, *args, **kwargs)', None))
    self.assertEqual(
        self.sanitize(failures[0].frames[1]),
        self.mk(
            '<lambda>',
            "(lambda check, steps, *args, **kwargs: check(('x' not in steps)))",
            {'steps.keys()': "['x']"}))


if __name__ == '__main__':
  sys.exit(test_env.main())
