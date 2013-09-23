# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'generator_script',
  'path'
]


def GenSteps(api):
  api.path.add_checkout(api.path.slave_build())
  yield api.generator_script('bogus')
  yield api.generator_script('bogus.py')


def GenTests(_api):
  yield 'basic', {
    'step_mocks': {
      'gen step(bogus)': {
        'json': {
          'output': [{'name': 'mock.step.binary',
                      'cmd': ['echo', 'mock step binary']}]
        }
      },
      'gen step(bogus.py)': {
        'json': {
          'output': [{'name': 'mock.step.python',
                      'cmd': ['echo', 'mock step python']}]
        }
      }
    }
  }
