# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'path',
  'platform',
  'step',
]


def RunSteps(api):
  api.step('step1',
                  ['/bin/echo', str(api.path['slave_build'].join('foo'))])

  # module.resource(...) demo.
  api.step('print resource',
           ['echo', api.path.resource('dir', 'file.py')])


def GenTests(api):
  # This line is for code coverage.
  api.path['slave_build'].join('foo')

  for platform in ('linux', 'win', 'mac'):
    yield api.test(platform) + api.platform.name(platform)
