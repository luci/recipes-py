#!/usr/bin/env python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import test_env  # pylint: disable=W0611
import unittest
import mock  # pylint: disable=F0401
with mock.patch('os.getcwd') as mock_getcwd:
  mock_getcwd.return_value = '/b/build/slave/fake_slave/build'
  from slave import recipe_util  # pylint: disable=F0401

class RecipeUtilGlobalTest(unittest.TestCase):

  def setUp(self):
    self.ru = recipe_util

  def test_depot_tools_path(self):
    self.assertEqual(self.ru.depot_tools_path(), '/b/depot_tools')
    self.assertEqual(self.ru.depot_tools_path('thingy', 'thingy.py'),
                     '/b/depot_tools/thingy/thingy.py')

    self.assertRaises(AssertionError,
        lambda: self.ru.depot_tools_path('some', '..', 'dumb', 'path'))

  def test_build_internal_path(self):
    self.assertEqual(self.ru.build_internal_path(), '/b/build_internal')
    self.assertEqual(self.ru.build_internal_path('thingy', 'thingy.py'),
                     '/b/build_internal/thingy/thingy.py')

  def test_build_path(self):
    self.assertEqual(self.ru.build_path(), '/b/build')
    self.assertEqual(self.ru.build_path('thingy', 'thingy.py'),
                     '/b/build/thingy/thingy.py')

  def test_slave_build_path(self):
    self.assertEqual(self.ru.slave_build_path(),
                     '/b/build/slave/fake_slave/build')
    self.assertEqual(self.ru.slave_build_path('thingy', 'thingy.py'),
                     '/b/build/slave/fake_slave/build/thingy/thingy.py')

  def test_checkout_path_raw(self):
    self.assertEqual(self.ru.checkout_path(), '%(CheckoutRootPlaceholder)s')
    self.assertEqual(self.ru.checkout_path('thingy', 'thingy.py'),
                     '%(CheckoutRootPlaceholder)s/thingy/thingy.py')


class RecipeUtilMirrorStepsTest(unittest.TestCase):

  def setUp(self):
    self.ru = recipe_util
    # Mirrored is default
    self.s_m = self.ru.Steps({})
    self.s   = self.ru.Steps({'use_mirror': False})

  def test_mirrorURLs(self):
    self.assertEqual(self.s_m.ChromiumSvnURL('trunk', 'src'),
                     'svn://svn-mirror.golo.chromium.org/chrome/trunk/src')
    self.assertEqual(self.s.ChromiumSvnURL('trunk', 'src'),
                     'https://src.chromium.org/chrome/trunk/src')

  def test_nonMirrorURLs(self):
    self.assertEqual(self.s_m.ChromiumGitURL('chromium', 'src'),
                     'https://chromium.googlesource.com/chromium/src')
    self.assertEqual(self.s.ChromiumGitURL('chromium', 'src'),
                     'https://chromium.googlesource.com/chromium/src')

  def test_mirror_only(self):
    self.assertEqual(self.s_m.mirror_only(['foobar', 'item']),
                     ['foobar', 'item'])
    self.assertEqual(self.s.mirror_only(['foobar', 'item']), [])

  def test_chromium_common_solution(self):
    self.assertEqual(
      self.s_m.gclient_common_solution('chromium'),
      {
        'name' : 'src',
        'url' : 'svn://svn-mirror.golo.chromium.org/chrome/trunk/src',
        'deps_file' : 'DEPS',
        'managed' : True,
        'custom_deps': {
          'src/third_party/WebKit/LayoutTests': None,
          'src/webkit/data/layout_tests/LayoutTests': None},
        'custom_vars': {
          'googlecode_url': 'svn://svn-mirror.golo.chromium.org/%s',
          'nacl_trunk': 'http://src.chromium.org/native_client/trunk',
          'sourceforge_url': 'svn://svn-mirror.golo.chromium.org/%(repo)s',
          'webkit_trunk':
          'svn://svn-mirror.golo.chromium.org/webkit-readonly/trunk'},
        'safesync_url': '',
      })
    self.assertEqual(
      self.s.gclient_common_solution('chromium'),
      {
        'name' : 'src',
        'url' : 'https://src.chromium.org/chrome/trunk/src',
        'deps_file' : 'DEPS',
        'managed' : True,
        'custom_deps': {
          'src/third_party/WebKit/LayoutTests': None,
          'src/webkit/data/layout_tests/LayoutTests': None},
        'custom_vars': {},
        'safesync_url': '',
      })

  def test_chromium_tools_build(self):
    tools_build = {
      'name': 'build',
      'url': 'https://chromium.googlesource.com/chromium/tools/build.git',
      'managed' : True,
      'deps_file' : '.DEPS.git',
    }
    self.assertEqual(self.s_m.gclient_common_solution('tools_build'),
                     tools_build)
    self.assertEqual(self.s.gclient_common_solution('tools_build'),
                     tools_build)


class RecipeUtilStepsTest(unittest.TestCase):

  def setUp(self):
    self.ru = recipe_util
    self.s = self.ru.Steps({
      'issue': '12345',
      'patchset': '1',
      'rietveld': 'https://rietveld.org'
    })

  def test_step(self):
    self.assertEqual(
      self.s.step('foobar', ['this', 'is', 'command']),
      {'name': 'foobar', 'cmd': ['this', 'is', 'command']})

    self.assertRaises(AssertionError,
        lambda: self.s.step('foobar', 'I am a shell command', shell=True))

  def test_apply_issue_step(self):
    self.assertEquals(
      self.s.apply_issue_step(),
      {'name': 'apply_issue',
       'cmd': [
         '/b/depot_tools/apply_issue',
         '-r', '%(CheckoutRootPlaceholder)s',
         '-i', '12345',
         '-p', '1',
         '-s', 'https://rietveld.org',
         '-e', 'commit-bot@chromium.org']})

  def test_git_step(self):
    self.assertEquals(
      self.s.git_step('rebase', '--onto', 'master'),
      {
        'name': 'git rebase',
        'cmd': [
          'git', '--work-tree', '%(CheckoutRootPlaceholder)s',
                 '--git-dir', '%(CheckoutRootPlaceholder)s/.git',
                 'rebase', '--onto', 'master']})

    # git config gets special treatment for the name
    self.assertEquals(
      self.s.git_step('config', 'user.name', 'dudeface'),
      {
        'name': 'git config user.name',
        'cmd': [
          'git', '--work-tree', '%(CheckoutRootPlaceholder)s',
                 '--git-dir', '%(CheckoutRootPlaceholder)s/.git',
                 'config', 'user.name', 'dudeface']})


if __name__ == '__main__':
  unittest.main()