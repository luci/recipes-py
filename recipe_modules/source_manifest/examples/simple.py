# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


DEPS = [
  'python',
  'source_manifest',
]


def RunSteps(api):
  api.python.succeeding_step('a step', 'Source manifest requires a step.')

  revision = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'.decode('hex')
  api.source_manifest.set_json_manifest('main_checkout', {
    'directories': {
      'src': {
        'git_checkout': {
          'repo_url': 'https://chromium.googlesource.com/chromium/src.git',
          'revision': revision,
        }
      }
    }
  })


def GenTests(api):
  yield api.test('basic')
