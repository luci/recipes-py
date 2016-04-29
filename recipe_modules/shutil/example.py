# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.types import freeze


DEPS = [
  'path',
  'shutil',
  'step',
]

TEST_CONTENTS = freeze({
  'simple': 'abcde',
  'spaces': 'abcde fgh',
  'symbols': '! ~&&',
  'multiline': '''ab
cd
efg
''',
})


def RunSteps(api):
  # remove demo.
  api.shutil.remove('foo', 'bar')

  # listdir demo.
  result = api.shutil.listdir('fake dir', '/fake/dir')
  for element in result:
    api.step('manipulate %s' % str(element), ['some', 'command'])

  # mkdtemp demo.
  for prefix in ('prefix_a', 'prefix_b'):
    # Create temp dir.
    temp_dir = api.path.mkdtemp(prefix)
    assert api.path.exists(temp_dir)
    # Make |temp_dir| surface in expectation files.
    api.step('print %s' % prefix, ['echo', temp_dir])

  for name, content in TEST_CONTENTS.iteritems():
    api.shutil.write('write_%s' % name, 'tmp_file.txt', content)
    actual_content = api.shutil.read(
        'read_%s' % name, 'tmp_file.txt',
        test_data=content
    )
    msg = 'expected %s but got %s' % (content, actual_content)
    assert actual_content == content, msg

  try:
    # copytree
    content = 'some file content'
    tmp_dir = api.path['tmp_base'].join('copytree_example_tmp')
    api.shutil.makedirs('makedirs', tmp_dir)
    path = tmp_dir.join('dummy_file')
    api.shutil.write('write %s' % path, path, content)
    new_tmp = api.path['tmp_base'].join('copytree_example_tmp2')
    new_path = new_tmp.join('dummy_file')
    api.shutil.copytree('copytree', tmp_dir, new_tmp)
    actual_content = api.shutil.read('read %s' % new_path, new_path,
                                   test_data=content)
    assert actual_content == content

    # glob.
    files = api.shutil.glob(
        'glob', tmp_dir.join('*'),
        test_data=[tmp_dir.join('dummy_file')])
    assert files == [str(tmp_dir.join('dummy_file'))], files

  finally:
    api.shutil.rmtree(tmp_dir, name='cleanup')
    api.shutil.rmtree(new_tmp, name='cleanup2')


def GenTests(api):
  yield api.test('basic')
