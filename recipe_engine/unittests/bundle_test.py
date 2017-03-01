#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import logging
import os
import re
import sys
import unittest
import posixpath

import test_env

import mock

from recipe_engine import bundle

logger = logging.getLogger()
logger.level = logging.DEBUG
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)

P = bundle.PosixPath
N = bundle.NativePath


def Pfix(thing):
  if isinstance(thing, str):
    return P(thing)
  if isinstance(thing, list):
    return map(P, thing)
  if isinstance(thing, set):
    return set(P(x) for x in thing)
  raise ValueError("unknown type: %s" % type(thing))


class TestSimpleGlobs(unittest.TestCase):
  def test_star(self):
    self.assertEqual(bundle.parse_simple_glob(P('a/b/*')),
                     (P('a/b'), r'.*\Z(?ms)'))

  def test_foostar(self):
    self.assertEqual(bundle.parse_simple_glob(P('a/b/foo*')),
                     (P('a/b'), r'foo.*\Z(?ms)'))

  def test_starfoostar(self):
    self.assertEqual(bundle.parse_simple_glob(P('a/b/*foo*')),
                     (P('a/b'), r'.*foo.*\Z(?ms)'))

  def test_no_prefix(self):
    self.assertEqual(bundle.parse_simple_glob(P('*foo*')),
                     (P(''), r'.*foo.*\Z(?ms)'))

  def test_bad_noglob(self):
    with self.assertRaises(ValueError):
      bundle.parse_simple_glob(P('foo'))

  def test_bad_mixedglob(self):
    with self.assertRaises(ValueError):
      bundle.parse_simple_glob(P('foo/*/bar'))

  def test_bad_prefixglob(self):
    with self.assertRaises(ValueError):
      bundle.parse_simple_glob(P('*/bar'))


FAKE_LS_TREE = '\n'.join([
  '100644 blob 302296b172eb2152d249734ed93690c7213f0ea0\t.gitignore',
  '040000 tree c7dcb4bbcdaf65ea75ea7735c7694d412f66ddb6\tAudio',
  '160000 commit 3bb7c33fbb5721e2be5ff963f8f3ba78e4878983\tLS_COLORS',
  '100644 blob 1402d9c72db11e48bb15a5c4163e5fbbbd1a6218\tREADME.md',
  '040000 tree a8fb7987b643a4f5a5bd2461190b112da5935cb0\tUltiSnips',
  '100644 blob b04aedfea3937aaa936d200a88f238f7199d2c13\tgitconfig',
  '120000 blob c9a3c9c4aaeabba0d32c33703463889b9aeb0459\tinit.vim',
  '040000 tree b1eeba79c8b60fc23a26f1b77f1e8d1d914e74ec\tkeymaps',
  '100644 blob 1bc319269e08407a2ca7dc48c86ac28a3dbd276c\tredshift.conf',
  '040000 tree ecae6ec749ba092757ffc0dc0216d681d3425d56\tsyntax',
  '040000 tree 26b8f34d01929afa776ad366d9070860557483a1\ttmp',
  '100644 blob 8f7c9a24b8428050b9467a1a55703f2a72cbcb2c\tvimrc',
  '100644 blob d62472f170adbfa6174d2a2329ab05e8b1f333ac\txmodmap',
  '040000 tree 945792404295e761af0a460dc61dddd1cd94bc7c\tzsh_custom',
  '040000 tree 945792404295e761af0a460dc61dddd1cd94bc7c\tgit_stuff',
  '100644 blob ade8a723cdededf200ab2e2dd4479145246ed6eb\tzshrc.extra',
  '100644 blob 9be6f9f1bc7cce55f858a7c6a5dd0bb62a6fd5c6\tzshrc.plugins',
])

class TestRepoReaders(unittest.TestCase):
  @mock.patch('subprocess.check_output')
  def test_repo_files_simple_pattern(self, check_output):
    check_output.return_value = FAKE_LS_TREE

    basedir, pattern = bundle.parse_simple_glob(P('some/dir/*git*'))

    out = list(bundle.repo_files_simple_pattern(N('some_root'), basedir,
                                                re.compile(pattern)))
    self.assertEqual(out, Pfix([
      'some/dir/.gitignore',
      'some/dir/gitconfig',
    ]))
    check_output.assert_has_calls([
      mock.call(['git', '-C', 'some_root', 'ls-tree',
                 'HEAD:'+basedir.raw_value])
    ])

  @mock.patch('recipe_engine.bundle.set_executable')
  @mock.patch('__builtin__.open', new_callable=mock.mock_open, create=True)
  @mock.patch('subprocess.check_call')
  @mock.patch('subprocess.check_output')
  def test_write_from_repo(self, check_output, check_call, mopen, set_ex):
    check_output.return_value = (
      '100755 blob ade8a723cdededf200ab2e2dd4479145246ed6eb\tzshrc.extra'
    )

    bundle.write_from_repo(N('some_root'), N('outdir'),
                           P('path/to/tzshrc.extra'))

    fake_file = mopen.return_value
    mopen.assert_called_once_with(
      os.path.join('outdir', 'path', 'to', 'tzshrc.extra'), 'wb')
    set_ex.assert_called_once_with(fake_file)
    check_call.assert_called_once_with(['git', '-C', 'some_root', 'cat-file',
                                        'blob', 'HEAD:path/to/tzshrc.extra'],
                                       stdout=fake_file)


class TestParseBundleExtra(unittest.TestCase):
  def test_parse_extra_files(self):
    data = '\n'.join([
      '# some comment',
      '',
      '//some_file',
      '//path/to/file',
      '//path/to_other',
    ])
    dirs, globs, files, errors = bundle.parse_bundle_extra(data)
    self.assertFalse(errors)
    self.assertEqual(files, Pfix(
      ['some_file', 'path/to/file', 'path/to_other']))
    self.assertEqual(dirs, [])
    self.assertDictEqual(globs, {})

  def test_parse_extra_dirs(self):
    data = '\n'.join([
      '  # some comment',
      '',
      '//',
      '//path/to/',
      '//path/to_dir/',
    ])
    dirs, globs, files, errors = bundle.parse_bundle_extra(data)
    self.assertFalse(errors)
    self.assertEqual(files, [])
    self.assertEqual(dirs, Pfix(['', 'path/to', 'path/to_dir']))
    self.assertDictEqual(globs, {})

  def test_parse_extra_globs(self):
    data = '\n'.join([
      '  # some comment',
      '',
      '//*stuff',
      '//path/to/stuff*',
      '//path/to/*others*',
      '//path/to/bob?',
      '//path/everything/*',
    ])
    dirs, globs, files, errors = bundle.parse_bundle_extra(data)
    self.assertFalse(errors)
    self.assertDictEqual(dict(globs), {
      P(''): {'.*stuff\\Z(?ms)'},
      P('path/everything'): {'.*\\Z(?ms)'},
      P('path/to'): {'.*others.*\\Z(?ms)', 'stuff.*\\Z(?ms)', 'bob.\\Z(?ms)'},
    })
    self.assertEqual(files, [])
    self.assertEqual(dirs, [])


  def test_parse_bad_path(self):
    data = '\n'.join([
      '//bad\\path',
      'no_prefix',
      '//sketchy/../path',
      '//*to*/many/globs*',
      '//to//much/slashes',
    ])
    _, _, _, errors = bundle.parse_bundle_extra(data)
    self.assertEquals(errors, [
      '''line 0: '//bad\\\\path' contains "\\" (use "/" instead)''',
      '''line 1: 'no_prefix' missing "//"''',
      '''line 2: '//sketchy/../path' relative path''',
      ('''line 3: '//*to*/many/globs*' not a simple glob '''
       '(non-leaf components are patterns)'),
      '''line 4: '//to//much/slashes' has doubled slashes''',
    ])


class TestMinifyExtraFiles(unittest.TestCase):
  def test_dirs_remove_files_and_globs(self):
    already_dirs = Pfix({'d', 'e/f'})
    dirs = Pfix({'a', 'b/c', 'b/c/d', 'e/f/g'})
    files = Pfix({'a/b/c', 'b/cow', 'extra'})
    globs = collections.defaultdict(list)
    def addGlob(pth):
      path, pattern = bundle.parse_simple_glob(P(pth))
      globs[path].append(pattern)
    addGlob('a/b/*x*')
    addGlob('neat*')
    addGlob('sub/*.go')
    addGlob('sub/*.py')
    addGlob('e/f/cool*')

    newDirs, newGlobs, newFiles = bundle.minify_extra_files(
      dirs, globs, files, already_dirs)

    self.assertEqual(newDirs, Pfix({'a', 'b/c'}))
    self.assertEqual({k: v.pattern for k, v in newGlobs.iteritems()}, {
      P(''): '(neat.*\\Z(?ms))',
      P('sub'): '(.*\.go\\Z(?ms))|(.*\.py\\Z(?ms))',
    })
    self.assertEqual(newFiles, Pfix({
      'b/cow', 'extra'
    }))

  def test_globs_remove_files(self):
    dirs = {}
    globs = collections.defaultdict(list)
    def addGlob(pth):
      path, pattern = bundle.parse_simple_glob(P(pth))
      globs[path].append(pattern)
    addGlob('a/b/*c*')
    addGlob('b*') # doesn't remove b/cow
    files = Pfix({'a/b/c', 'b/cow', 'extra'})

    newDirs, newGlobs, newFiles = bundle.minify_extra_files(
      dirs, globs, files, set())

    self.assertEqual(newDirs, set())
    self.assertEqual({k: v.pattern for k, v in newGlobs.iteritems()}, {
      P(''): '(b.*\\Z(?ms))',
      P('a/b'): '(.*c.*\\Z(?ms))',
    })
    self.assertEqual(newFiles, Pfix({
      'b/cow', 'extra'
    }))

  def test_full_repo(self):
    already_dirs = Pfix({'d', 'e/f'})
    dirs = Pfix({'', 'a', 'b/c', 'b/c/d', 'e/f/g'})
    files = Pfix({'a/b/c', 'b/cow', 'extra'})
    globs = collections.defaultdict(list)
    def addGlob(pth):
      path, pattern = bundle.parse_simple_glob(P(pth))
      globs[path].append(pattern)
    addGlob('a/b/*x*')
    addGlob('neat*')
    addGlob('sub/*.go')
    addGlob('sub/*.py')
    addGlob('e/f/cool*')

    newDirs, newGlobs, newFiles = bundle.minify_extra_files(
      dirs, globs, files, already_dirs)

    self.assertEqual(newDirs, {P('')})
    self.assertEqual({k: v.pattern for k, v in newGlobs.iteritems()}, {})
    self.assertEqual(newFiles, set())


def repo_files_recursive_mock(spec):
  """Assign to the .side_effect of the mock fo repo_files_recursive.

  Spec is a dictionary of `relpath` to files in that path which should be
  mocked.
  """
  spec = {P(k): map(P, v) for k, v in spec.iteritems()}

  def _mock(_repo_root, relpath):
    assert relpath in spec, '%r not in %r' % (relpath, spec.keys())
    for fragment in spec[relpath]:
      yield relpath.join(fragment)
  return _mock


def repo_files_simple_pattern_mock(spec):
  """Assign to the .side_effect of the mock fo repo_files_simple_pattern_mock.

  Spec is a dictionary of `dirpath` to files in that path which should be
  mocked.
  """
  spec = {P(k): map(P, v) for k, v in spec.iteritems()}

  def _mock(_repo_root, dirpath, pattern):
    assert dirpath in spec, '%r not in %r' % (dirpath, spec.keys())
    for fragment in spec[dirpath]:
      if '/' not in fragment.raw_value and pattern.match(fragment.raw_value):
        yield dirpath.join(fragment)
  return _mock


def read_from_repo_mock(spec):
  """Assign to the .side_effect of the mock fo read_from_repo.

  Spec is a dictionary of `path` to file content. File content may either be
  a string or a list of strings. If it's a list of strings, they'll be joined
  with newlines.
  """
  spec = {
    P(k): ('\n'.join(v) if isinstance(v, list) else v)
    for k, v in spec.iteritems()
  }

  def _mock(_repo_root, relpath):
    assert relpath in spec, '%r not in %r' % (relpath, spec.keys())
    return spec[relpath]
  return _mock


class TestGenerateFiles(unittest.TestCase):
  @mock.patch('recipe_engine.bundle.repo_files_recursive')
  @mock.patch('recipe_engine.bundle.repo_files_simple_pattern')
  @mock.patch('recipe_engine.bundle.read_from_repo')
  def test_generate_files(self, read_repo, rf_sp, rf_rec):
    self.maxDiff = None
    spec = {
      'rel_recipe_dir/recipes': [
        'foo.py',
        'foo.resources/some/script.py',
        'foo.expected/basic.json',
        'foo.expected/other.json',
      ],
      'rel_recipe_dir/recipe_modules': [
        'bar/__init__.py',
        'bar/api.py',
        'bar/extra.py',
        'bar/resources/some/script.py',

        'baz/__init__.py',
        'baz/api.py',
        'baz/bundle_extra_paths.txt',

        'cool/__init__.py',
        'cool/api.py',
        'cool/bundle_extra_paths.txt',
      ],
      'root_dir/subdir': [
        'bazfile1',
        '_bazfile2',
        'bogus_file',
        'coolfile1',
        'coolfile2',
      ],
      'rel_recipe_dir/subdir': [
        'bogus_file',
        'pattern_foo/subdir',
        'pattern_file',
      ],
      'other_dir': [
        'a',
        'b',
      ],
    }

    rf_sp.side_effect = repo_files_simple_pattern_mock(spec)
    rf_rec.side_effect = repo_files_recursive_mock(spec)
    read_repo.side_effect = read_from_repo_mock({
      'rel_recipe_dir/recipe_modules/baz/bundle_extra_paths.txt': [
        '//rel_recipe_dir/subdir/*pattern*',
        '//other_dir/',
        '//rel_recipe_dir/recipes/foo.py',  # already covered
        '//some_base_file',
        '//root_dir/subdir/*baz*',
      ],

      'rel_recipe_dir/recipe_modules/cool/bundle_extra_paths.txt': [
        '//root_dir/subdir/cool*',
      ]
    })

    files = list(bundle.generate_files(
      N('fake_root'), P('rel_recipe_dir'), True))
    self.assertEqual(files, Pfix([
      'rel_recipe_dir/recipe_modules/bar/__init__.py',
      'rel_recipe_dir/recipe_modules/bar/api.py',
      'rel_recipe_dir/recipe_modules/bar/extra.py',
      'rel_recipe_dir/recipe_modules/bar/resources/some/script.py',
      'rel_recipe_dir/recipe_modules/baz/__init__.py',
      'rel_recipe_dir/recipe_modules/baz/api.py',
      'rel_recipe_dir/recipe_modules/baz/bundle_extra_paths.txt',
      'rel_recipe_dir/recipe_modules/cool/__init__.py',
      'rel_recipe_dir/recipe_modules/cool/api.py',
      'rel_recipe_dir/recipe_modules/cool/bundle_extra_paths.txt',
      'rel_recipe_dir/recipes/foo.py',
      'rel_recipe_dir/recipes/foo.resources/some/script.py',
      'other_dir/a',
      'other_dir/b',
      'root_dir/subdir/bazfile1',
      'root_dir/subdir/_bazfile2',
      'root_dir/subdir/coolfile1',
      'root_dir/subdir/coolfile2',
      'rel_recipe_dir/subdir/pattern_file',
      'some_base_file',
    ]))


if __name__ == '__main__':
  sys.exit(unittest.main())
