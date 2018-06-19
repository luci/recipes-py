#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys
import unittest

from collections import OrderedDict

import test_env

from recipe_engine import post_process
from recipe_engine import checker


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


class TestFilter(unittest.TestCase):
  def setUp(self):
    self.d = mkD('a', 'b', 'b.sub', 'b.sub2')
    self.f = post_process.Filter

  def test_basic(self):
    c = checker.Checker('<filename>', 0, lambda: None, (), {})
    self.assertEqual(
      self.f('a', 'b')(c, self.d), mkD('a', 'b'))
    self.assertEqual(len(c.failed_checks), 0)

  def test_built(self):
    c = checker.Checker('<filename>', 0, lambda: None, (), {})
    f = self.f()
    f = f.include('b')
    f = f.include('a')
    self.assertEqual(f(c, self.d), mkD('a', 'b'))
    self.assertEqual(len(c.failed_checks), 0)

  def test_built_fields(self):
    c = checker.Checker('<filename>', 0, lambda: None, (), {})
    f = self.f()
    f = f.include('b', ['sub_b'])
    f = f.include('a', ['sub_a'])
    self.assertEqual(f(c, self.d), OrderedDict([
      ('a', mkS('a', 'sub_a')),
      ('b', mkS('b', 'sub_b')),
    ]))
    self.assertEqual(len(c.failed_checks), 0)

  def test_built_extra_includes(self):
    f = self.f('a', 'b', 'x')
    c = checker.Checker('<filename>', 0, f, (), {})
    self.assertEqual(f(c, self.d), mkD('a', 'b'))
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(c.failed_checks[0].frames[-1].code,
                     'check((len(unused_includes) == 0))')
    self.assertEqual(c.failed_checks[0].frames[-1].varmap,
                     {'unused_includes': "{'x': ()}"})

  def test_re(self):
    f = self.f().include_re('b\.')
    c = checker.Checker('<filename>', 0, f, (), {})
    self.assertEqual(f(c, self.d), mkD('b.sub', 'b.sub2'))
    self.assertEqual(len(c.failed_checks), 0)

  def test_re_low_limit(self):
    f = self.f().include_re('b\.', at_least=3)
    c = checker.Checker('<filename>', 0, f, (), {})
    self.assertEqual(f(c, self.d), mkD('b.sub', 'b.sub2'))
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(c.failed_checks[0].frames[-1].code,
                     'check((re_usage_count[regex] >= at_least))')
    self.assertEqual(c.failed_checks[0].frames[-1].varmap,
                     {'at_least': '3',
                      're_usage_count[regex]': '2',
                      'regex': "re.compile('b\\\\.')"})

  def test_re_high_limit(self):
    f = self.f().include_re('b\.', at_most=1)
    c = checker.Checker('<filename>', 0, f, (), {})
    self.assertEqual(f(c, self.d), mkD('b.sub', 'b.sub2'))
    self.assertEqual(len(c.failed_checks), 1)
    self.assertEqual(c.failed_checks[0].frames[-1].code,
                     'check((re_usage_count[regex] <= at_most))')
    self.assertEqual(c.failed_checks[0].frames[-1].varmap,
                     {'at_most': '1',
                      're_usage_count[regex]': '2',
                      'regex': "re.compile('b\\\\.')"})


class TestRun(unittest.TestCase):
  def setUp(self):
    self.d = mkD('a', 'b', 'b.sub', 'b.sub2')

  def expect_fails(self, num_fails, func, *args, **kwargs):
    c = checker.Checker('<filename>', 0, func, args, kwargs)
    func(c, self.d, *args, **kwargs)
    self.assertEqual(len(c.failed_checks), num_fails)

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


if __name__ == '__main__':
  sys.exit(unittest.main())
