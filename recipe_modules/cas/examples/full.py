# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'cas',
    'file',
    'path',
    'properties',
    'runtime',
    'step',
]


def RunSteps(api):
  api.cas.instance

  # Prepare files.
  temp = api.path.mkdtemp('cas-example')
  api.step('touch a', ['touch', temp.join('a')])
  api.step('touch b', ['touch', temp.join('b')])
  api.file.ensure_directory('mkdirs', temp.join('sub', 'dir'))
  api.step('touch d', ['touch', temp.join('sub', 'dir', 'd')])

  digest = api.cas.archive('archive', temp,
                           *[temp.join(p) for p in ('a', 'b', 'sub')])
  # You can also archive the entire directory.
  api.cas.archive('archive directory', temp)

  out = api.path.mkdtemp('cas-output')
  api.cas.download('download', digest, out)


def GenTests(api):
  yield api.test('basic')
  yield api.test('experimental') + api.runtime(is_experimental=True)
