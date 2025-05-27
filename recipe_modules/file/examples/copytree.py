# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.file.examples.copytree import Properties

DEPS = [
    "file",
    "path",
    "properties",
]

PROPERTIES = Properties


def RunSteps(api, properties):
  file_names = ['a', 'aa', 'b', 'bb', 'c', 'cc']

  test_base_dir = api.path.mkdtemp()

  dest = test_base_dir / 'some dir'
  api.file.ensure_directory('ensure "some dir"', dest)
  for fname in file_names:
    api.file.write_text('write %s' % fname, dest / fname, fname)
  api.file.symlink('create symlink', dest / 'bb', dest / 'symlink_bb')
  api.file.filesizes('check filesizes', [dest / f for f in file_names])

  dest2 = test_base_dir / 'some other dir'
  api.file.rmtree('make sure dest is gone', dest2)
  if properties.allow_override:
    api.file.ensure_directory('ensure "some other dir"', dest2)
    api.file.write_text('write subdir/a', dest2 / 'a',
                        'This text should be overridden.')

  # Note: on test, actual copying is done by the mock method, so that the
  # arguments don't matter.
  api.file.copytree(
      'copy it',
      dest,
      dest2,
      symlinks=properties.symlinks,
      hardlink=properties.hardlink,
      allow_override=properties.allow_override)

  dest_file_names = file_names + ['symlink_bb']
  paths = api.file.listdir('list new dir', dest2, test_data=dest_file_names)
  assert paths == [dest2 / n for n in dest_file_names], paths

  paths = api.file.glob_paths('glob *a', dest2, '*a', test_data=['a', 'aa'])
  assert paths == [dest2 / 'a', dest2 / 'aa'], paths

  for pth in paths:
    assert api.file.read_text('read %s' % pth, pth, pth.name)

  assert api.file.read_text('read %s' % pth, dest2 / 'symlink_bb', 'bb')

  api.file.remove('rm a', dest2 / 'a')
  paths = api.file.glob_paths('glob *a', dest2, '*a', test_data=['aa'])
  assert paths == [dest2 / 'aa'], paths

  api.file.rmglob('rm *b', dest2, '*b')
  paths = api.file.listdir('list new dir', dest2, test_data=['aa', 'c', 'cc'])
  assert paths == [dest2 / p for p in ['aa', 'c', 'cc']], paths

  api.file.rmcontents('remove "some other dir/*"', dest2)
  assert api.path.exists(dest2), dest2


def GenTests(api):
  yield api.test('basic', api.properties(Properties(hardlink=False)))
  yield api.test('hardlink', api.properties(Properties(hardlink=True)))
  yield api.test('symlinks', api.properties(Properties(symlinks=True)))

  yield api.test(
      'existing-dirs',
      api.properties(Properties(hardlink=False, allow_override=True)),
  )
