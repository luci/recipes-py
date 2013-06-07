#!/usr/bin/env python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import test_env  # pylint: disable=W0611

import coverage
import os
import unittest


class RecipeUtilApiTest(unittest.TestCase):
  def setUp(self):
    from slave import recipe_util  # pylint: disable=F0401
    self.s = recipe_util.RecipeApi({
      'issue': '12345',
      'patchset': '1',
      'rietveld': 'https://rietveld.org'
    }, mock_paths=[])

  def test_depot_tools_path(self):
    self.assertEqual(self.s.depot_tools_path(), '[DEPOT_TOOLS_ROOT]')
    self.assertEqual(self.s.depot_tools_path('thingy', 'thingy.py'),
                     '[DEPOT_TOOLS_ROOT]/thingy/thingy.py')

    self.assertRaises(AssertionError,
        lambda: self.s.depot_tools_path('some', '..', 'dumb', 'path'))

  def test_build_internal_path(self):
    self.assertEqual(self.s.build_internal_path(), '[BUILD_INTERNAL_ROOT]')
    self.assertEqual(self.s.build_internal_path('thingy', 'thingy.py'),
                     '[BUILD_INTERNAL_ROOT]/thingy/thingy.py')

  def test_build_path(self):
    self.assertEqual(self.s.build_path(), '[BUILD_ROOT]')
    self.assertEqual(self.s.build_path('thingy', 'thingy.py'),
                     '[BUILD_ROOT]/thingy/thingy.py')

  def test_slave_build_path(self):
    self.assertEqual(self.s.slave_build_path(),
                     '[SLAVE_BUILD_ROOT]')
    self.assertEqual(self.s.slave_build_path('thingy', 'thingy.py'),
                     '[SLAVE_BUILD_ROOT]/thingy/thingy.py')

  def test_checkout_path_raw(self):
    self.assertEqual(self.s.checkout_path(), '%(CheckoutRootPlaceholder)s')
    self.assertEqual(self.s.checkout_path('thingy', 'thingy.py'),
                     '%(CheckoutRootPlaceholder)s/thingy/thingy.py')

  def test_step(self):
    self.assertEqual(
      self.s.step('foobar', ['this', 'is', 'command']),
      {'name': 'foobar', 'cmd': ['this', 'is', 'command']})

    self.assertRaises(AssertionError,
        lambda: self.s.step('foobar', 'I am a shell command', shell=True))

  def test_apply_issue_step(self):
    self.assertEquals(
      self.s.apply_issue(),
      {'name': 'apply_issue',
       'cmd': [
         '[DEPOT_TOOLS_ROOT]/apply_issue',
         '-r', '%(CheckoutRootPlaceholder)s',
         '-i', '12345',
         '-p', '1',
         '-s', 'https://rietveld.org',
         '-e', 'commit-bot@chromium.org']})
    self.assertEquals(
      self.s.apply_issue('foobar', 'other'),
      {'name': 'apply_issue',
       'cmd': [
         '[DEPOT_TOOLS_ROOT]/apply_issue',
         '-r', '%(CheckoutRootPlaceholder)s/foobar/other',
         '-i', '12345',
         '-p', '1',
         '-s', 'https://rietveld.org',
         '-e', 'commit-bot@chromium.org']})

  def test_git(self):
    self.assertEquals(
      self.s.git('rebase', '--onto', 'master'),
      {
        'name': 'git rebase',
        'cmd': [
          'git', 'rebase', '--onto', 'master'],
        'cwd': '%(CheckoutRootPlaceholder)s'})

    # git config gets special treatment for the name
    self.assertEquals(
      self.s.git('config', 'user.name', 'dudeface'),
      {
        'name': 'git config user.name',
        'cmd': [
          'git', 'config', 'user.name', 'dudeface'],
        'cwd': '%(CheckoutRootPlaceholder)s'})


if __name__ == '__main__':
  cov = coverage.coverage(include=os.path.join(
    os.path.dirname(__file__), os.pardir, 'recipe_util.py'))
  cov.start()
  try:
    unittest.main()
  finally:
    cov.stop()
    cov.report()
