# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'file',
    'isolated',
    'json',
    'path',
    'step',
]


def RunSteps(api):
  # Inspect the associated isolated server.
  api.isolated.isolate_server

  # Prepare files.
  temp = api.path.mkdtemp('isolated-example')
  api.step('touch a', ['touch', temp.join('a')])
  api.step('touch b', ['touch', temp.join('b')])
  api.step('touch c', ['touch', temp.join('c')])
  api.file.ensure_directory('mkdirs', temp.join('sub', 'dir'))
  api.step('touch d', ['touch', temp.join('sub', 'dir', 'd')])

  # Create an isolated.
  isolated = api.isolated.isolated(temp)
  isolated.add_file(temp.join('a'))
  isolated.add_files([temp.join('b'), temp.join('c')])
  isolated.add_dir(temp.join('sub', 'dir'))

  # Archive with the default isolate server.
  isolated.archive('archiving')
  # Or, archive with
  isolated.archive('archiving elsewhere',
                   isolate_server='other-isolateserver.appspot.com')

  # You can also run an arbitrary command.
  api.isolated.run('isolated version', ['version'])


def GenTests(api):
  yield api.test('basic') + api.isolated.default_properties
