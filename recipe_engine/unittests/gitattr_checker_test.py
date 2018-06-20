#!/usr/bin/env vpython
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import shutil
import subprocess
import tempfile
import unittest

import test_env

from recipe_engine import gitattr_checker


class TestAttrChecker(unittest.TestCase):
  def setUp(self):
    self.git_repo = tempfile.mkdtemp()
    self.git('init', '-q')
    self.attr_checker = gitattr_checker.AttrChecker(self.git_repo)

  def tearDown(self):
    shutil.rmtree(self.git_repo)

  def git(self, *cmd, **kwargs):
    stdin = kwargs.pop('stdin', None)
    if stdin:
      kwargs['stdin'] = subprocess.PIPE
    kwargs.setdefault('stdout', subprocess.PIPE)
    kwargs.setdefault('stderr', subprocess.PIPE)
    kwargs.setdefault('cwd', self.git_repo)
    p = subprocess.Popen(['git'] + list(cmd), **kwargs)
    stdout, stderr = p.communicate(stdin)
    self.assertEqual(p.returncode, 0, stderr)
    return stdout.strip()

  def write(self, path, contents):
    file_path = os.path.join(self.git_repo, path)
    dirname = os.path.dirname(file_path)
    if dirname and not os.path.exists(dirname):
      os.makedirs(dirname)
    with open(os.path.join(self.git_repo, path), 'w') as f:
      f.write('\n'.join(contents))

  def commit(self):
    self.git('add', '-A')
    self.git('commit', '-m', 'foo')
    return self.git('rev-parse', 'HEAD')

  def getRecipeAttrValue(self, revision, files):
    self.git('checkout', revision)
    output = self.git('check-attr', '-z', '--stdin', 'recipes',
                      stdin='\0'.join(files))
    # The format of the data returned by check-attr -z is:
    #
    #   <path> NUL <attribute> NUL <info> NUL <path2> NUL <attribute> NUL ...
    #
    # Where info is the value of the attribute ('set', 'unset', 'unspecified').
    # In particular, there are no newlines separating records. Every third NUL
    # byte indicates a new record, so we take the 3rd field (index 2) jumping
    # three fields each line to yield a list with just the <info> fields.
    return [
        attr_value not in ('unset', 'unspecified')
        for attr_value in output.split('\0')[2::3]
    ]

  def assertEqualAttr(self, revision, files):
    actual = [self.attr_checker.check_file(revision, f) for f in files]
    expected = self.getRecipeAttrValue(revision, files)
    self.assertEqual(actual, expected)

  def testComments(self):
    self.write('.gitattributes',
               ['# Some comment',
                r'\# recipes',
                '',
                '/foo recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['#', '#foo', 'foo', 'foo#', 'bar/foo', 'bar/#', 'bar/foo#',
         'bar/#foo'])

  def testBang(self):
    self.write('.gitattributes',
               [r'\!foo recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['!foo', 'foo', 'bar'])

  def testSpecialCharacters(self):
    """Test that characters like . + and $ are handled correctly."""
    self.write('.gitattributes',
               ['foo.bar recipes',
                'ab+ recipes',
                'x^y$z recipes',
                '(paren*) recipes',
                'this|that recipes',
                r's\wt recipes',
                r'\[hello] recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo.bar', 'fooxbar', 'foobar',
         'ab+', 'abb', 'abc', 'ab',
         'y' 'x^y', 'y$z', 'x^y$z',
         '(parent)', '(paren)', 'parent', 'paren', '(paren))',
         'this', 'that', 'this|that',
         's t', r's\wt',
         'h', 'e', 'l', 'o', '[', '[hello]'])

  def testCharClass(self):
    self.write('.gitattributes',
               ['[]a] recipes',
                r'[0\-9] recipes',
                '[A-Z]* recipes',
                '[x*] recipes',
                '[l?] recipes',
                'fo[^o] recipes',
                'ba[^^] recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        [']', 'a', 'a]',
         '0', '1', '9', '-',
         'A', 'B', 'C', 'Z', 'AB', 'Ax', 'Axyzw', 'A/xyz',
         'x', '*', 'xx', 'xy',
         'l', '?', 'la', 'l^',
         'foo', 'fox',
         'bar', 'ba^'])

  def testQuotedPattern(self):
    self.write('.gitattributes',
               ['"space file" recipes',
                '"foo bar.*" recipes',
                'inside"?"quote recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['space file', 'space  file', 'space file.txt', 'foo/space file',
         'foo bar.', 'foo bar.txt', 'foo barx.txt', 'foo', 'bar.txt',
         'inside quote', 'inside.quote', 'inside  quote', 'inside"?"quote',
         'inside" "quote', 'inside""quote'])

  def testDoubleStars(self):
    # Test /**/
    self.write('.gitattributes',
               ['/**/foo recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'foo/bar', 'bar/foo', 'bar/x/foo', 'bar/xfoo', 'bar/foox'])

    self.write('.gitattributes',
               ['foo/**/bar recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'foo/bar', 'foo/baz/bar', 'foo/x/baz/bar', 'foox/bar',
         'foo/xbar', 'xfoo/bar', 'foo/xbar'])

    # Test **/
    self.write('.gitattributes',
               ['**/foo recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar/foo', 'foo/bar', 'bar/foo/baz', 'bar', 'bar/foox',
         'bar/xfoo'])

    # Test /**
    self.write('.gitattributes',
               ['/** recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'foo/bar', 'foo/bar/baz'])

    self.write('.gitattributes',
               ['foo/** recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'foo/bar', 'foo/bar/baz', 'foox/bar', 'xfoo/bar'])

  def testStar(self):
    self.write('.gitattributes',
               ['* recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'foo/bar', 'foo/bar/baz'])

    self.write('.gitattributes',
               ['foo* recipes',
                '*bar recipes',
                'b*az recipes',
                '*mu* recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'foox', 'xfoo', 'foxo', 'foo/x', 'x/foo', 'x/xfoo', 'x/foox',
         'bar', 'barx', 'xbar', 'baxa', 'bar/x', 'x/bar', 'x/xbar', 'x/barx',
         'baz', 'bazx', 'xbaz', 'baxz', 'bxaz', 'baz/x', 'x/baz', 'x/xbaz',
         'x/bazx', 'mu', 'lemur', 'mur', 'lemur', 'x/lemur', 'lemur/x'])

  def testEscapedStar(self):
    self.write('.gitattributes',
               [r'foo\* recipes',
                r'baz/\** recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'foo*', 'foox', 'bar/foo', 'bar/foo*', 'bar/foox', 'baz/x',
         'baz/*x', 'baz/*', 'baz/x/y', 'baz/*x/y'])

  def testQuestionMark(self):
    self.write('.gitattributes',
               ['f?o recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'fao', 'f o', 'fo', 'bar/foo', 'bar/fo', 'bar/f o'])

  def testAbsolutePath(self):
    self.write('.gitattributes',
               ['/*foo',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'xfoo', 'foox', 'bar/foo', 'bar/xfoo', 'bar/foox'])

  def testLastAttributeTakesPrecedence(self):
    self.write('.gitattributes',
               ['foo recipes -recipes !recipes',
                'bar -recipes recipes !recipes',
                'baz !recipes -recipes recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'baz', 'foo/bar', 'bar/foo', 'baz/bar', 'baz/foo',
         'bar/foo/baz'])

  def testLastLineTakesPrecedence(self):
    self.write('.gitattributes',
               ['/bar/** recipes',
                '/bar/foo/** -recipes',
                '/bar/baz/** !recipes',
                '/bar/foo/x recipes',
                'batman recipes',
                '/batman -recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['bar', 'bar/x', 'bar/y/z', 'bar/foo/x', 'bar/foo/y', 'bar/baz/x',
         'bar/baz/y/z', 'batman', 'nananananananana/batman'])

  def testMoreSpecificTakesPrecedence(self):
    self.write('.gitattributes',
               ['foo !recipes',
                'bar -recipes',])
    self.write('a/.gitattributes',
               ['foo -recipes',
                'bar !recipes',
                'baz recipes',])
    self.write('a/b/.gitattributes',
               ['foo recipes',
                'bar recipes',])
    revision = self.commit()
    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'baz', 'a/foo', 'a/bar', 'a/baz', 'a/b/foo', 'a/b/bar',
         'a/b/baz', 'a/b/c/foo', 'a/b/c/bar', 'a/b/c/baz'])

  def testProcessesTheRightRevision(self):
    self.write('.gitattributes',
               ['foo recipes',
                'bar recipes',
                'bar/foo !recipes',])
    revision = self.commit()

    self.write('.gitattributes',
               ['foo recipes',
                'bar recipes',])
    self.commit()

    self.assertEqualAttr(
        revision,
        ['foo', 'bar', 'bar/foo', 'foo/bar', 'bar/foo/baz'])



if __name__ == '__main__':
  unittest.main()
