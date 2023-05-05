# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
]


def RunSteps(api):
  file_names = ['a', 'aa', 'b', 'bb', 'c', 'cc']

  dest = api.path['start_dir'].join('some dir')
  api.file.ensure_directory('ensure "some dir"', dest)
  for fname in file_names:
    api.file.write_text('write %s' % fname, dest.join(fname), fname)
  api.file.filesizes('check filesizes', [dest.join(f) for f in file_names])

  dest2 = api.path['start_dir'].join('some other dir')
  api.file.rmtree('make sure dest is gone', dest2)
  api.file.copytree('copy it', dest, dest2)

  paths = api.file.listdir('list new dir', dest2, test_data=file_names)
  assert paths == [dest2.join(n) for n in file_names], paths

  paths = api.file.glob_paths('glob *a', dest2, '*a', test_data=['a', 'aa'])
  assert paths == [dest2.join('a'), dest2.join('aa')], paths

  for pth in paths:
    assert api.file.read_text('read %s' % pth, pth, api.path.basename(pth))

  api.file.remove('rm a', dest2.join('a'))
  paths = api.file.glob_paths('glob *a', dest2, '*a', test_data=['aa'])
  assert paths == [dest2.join('aa')], paths

  api.file.rmglob('rm b*', dest2, 'b*')
  paths = api.file.listdir('list new dir', dest2, test_data=['aa', 'c', 'cc'])
  assert paths == [dest2.join(p) for p in ['aa', 'c', 'cc']], paths

  api.file.rmcontents('remove "some other dir/*"', dest2)
  assert api.path.exists(dest2), dest2



def GenTests(api):
  yield api.test('basic')

