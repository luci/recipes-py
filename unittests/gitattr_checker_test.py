#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import os
import shutil
import subprocess

from unittest import mock

import test_env

from recipe_engine.internal import gitattr_checker


class AttrCheckerEquivalenceTests(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super().setUp()
    self.git_repo = self.tempdir()
    self.git('init', '-q')
    self.attr_checker = gitattr_checker.AttrChecker(self.git_repo, False)

  def git(self, *cmd, **kwargs):
    stdin = kwargs.pop('stdin', None)
    if stdin:
      kwargs['stdin'] = subprocess.PIPE
    kwargs.setdefault('stdout', subprocess.PIPE)
    kwargs.setdefault('stderr', subprocess.PIPE)
    kwargs.setdefault('cwd', self.git_repo)
    kwargs.setdefault('text', True)
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
    actual = self.attr_checker.check_files(revision, files)
    expected = self.getRecipeAttrValue(revision, files)
    self.assertDictEqual(dict(zip(files, actual)), dict(zip(files, expected)))

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


class AttrCheckerMockTests(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super().setUp()
    self._attr_checker = gitattr_checker.AttrChecker('repo', False)
    self._blobs = {
        'blob1': [
            'foo recipes',
            'bar lemur',
        ],
        'blob2': [
            'Neque porro quisquam est qui dolorem ipsum quia dolor',
            'sit amet, consectetur, adipisci velit',
        ],
        'blob3': [
            'foo -recipes',
            'foo lemur',
        ],
        'blob4': [
            'foo recipes',
            'bar recipes',
        ],
    }
    self._tree = {
        'rev1': {
            '.gitattributes': 'blob1',
            'irrelevant/lorem-ipsum.txt': 'blob2',
            'irrelevant/.gitattributes': 'blob4',
        },
        'rev2': {
            '.gitattributes': 'blob1',
        },
        'rev3': {
            '.gitattributes': 'blob1',
            'baz/.gitattributes': 'blob3',
        },
        'rev4': {
            '.gitattributes': 'blob4',
            'baz/.gitattributes': 'blob3',
        },
        'rev5': {
            'irrelevant/lorem-ipsum.txt': 'blob2',
            'irrelevant/.gitattributes': 'blob4',
        },
    }
    self._git_mock = mock.Mock()
    self._git_mock.side_effect = self._fake_git
    mock.patch('recipe_engine.internal.gitattr_checker.AttrChecker._git',
               self._git_mock).start()
    self.addCleanup(mock.patch.stopall)

  def _fake_git(self, cmd, stdin=None):
    self.assertEqual(cmd[0], 'cat-file')
    if not cmd[1].startswith('--batch-check'):
      return self._blobs[cmd[-1]]
    self.assertIsNotNone(stdin)
    result = []
    for line in stdin.splitlines():
      rev, path = line.split(':')
      if path not in self._tree[rev]:
        result.append(line + ' missing')
      else:
        result.append(self._tree[rev][path])
    return result

  def assertNewCalls(self, expected_calls):
    self.assertEqual(self._git_mock.mock_calls, expected_calls)
    self._git_mock.reset_mock()

  def testDoesntQueryNonGitattributesFiles(self):
    # We should only ask information about the .gitattributes files that affect
    # the modified files.
    self.assertEqual(
        self._attr_checker.check_files('rev1', ['foo', 'bar', 'baz/foo']),
        [True, False, True]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev1:.gitattributes\nrev1:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob1']),
    ])

  def testCachesGitattributesFiles(self):
    self.assertEqual(
        self._attr_checker.check_files('rev1', ['foo', 'bar', 'baz/foo']),
        [True, False, True]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev1:.gitattributes\nrev1:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob1']),
    ])

    # The revision changed, but the .gitattributes files did not. We shouldn't
    # ask git for information about file blobs.
    self.assertEqual(
        self._attr_checker.check_files('rev2', ['foo', 'bar', 'baz/foo']),
        [True, False, True]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev2:.gitattributes\nrev2:baz/.gitattributes'),
    ])

  def testQueriesNewGitattributesFile(self):
    self.assertEqual(
        self._attr_checker.check_files('rev2', ['foo', 'bar', 'baz/foo']),
        [True, False, True]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev2:.gitattributes\nrev2:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob1']),
    ])

    # A new .gitattribute file was added, but the old one hasn't changed.
    self.assertEqual(
        self._attr_checker.check_files('rev3', ['foo', 'bar', 'baz/foo']),
        [True, False, False]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev3:.gitattributes\nrev3:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob3']),
    ])

  def testQueriesModifiedGitattributesFile(self):
    self.assertEqual(
        self._attr_checker.check_files('rev3', ['foo', 'bar', 'baz/foo']),
        [True, False, False]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev3:.gitattributes\nrev3:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob1']),
        mock.call(['cat-file', 'blob', 'blob3']),
    ])

    # The .gitattribute file was modified
    self.assertEqual(
        self._attr_checker.check_files('rev4', ['foo', 'bar', 'baz/foo']),
        [True, True, False]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev4:.gitattributes\nrev4:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob4']),
    ])

  def testDeletedGitattributesFile(self):
    self.assertEqual(
        self._attr_checker.check_files('rev1', ['foo', 'bar', 'baz/foo']),
        [True, False, True]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev1:.gitattributes\nrev1:baz/.gitattributes'),
        mock.call(['cat-file', 'blob', 'blob1']),
    ])

    # The .gitattribute file was deleted
    self.assertEqual(
        self._attr_checker.check_files('rev5', ['foo', 'bar', 'baz/foo']),
        [False, False, False]
    )
    self.assertNewCalls([
        mock.call(['cat-file', '--batch-check=%(objectname)'],
                  'rev5:.gitattributes\nrev5:baz/.gitattributes'),
    ])


if __name__ == '__main__':
  test_env.main()
