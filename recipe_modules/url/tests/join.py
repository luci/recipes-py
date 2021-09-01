# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
  'step',
  'url',
]


def RunSteps(api):
  api.step('step1',
           ['/bin/echo', api.url.join('foo', 'bar', 'baz')])
  api.step('step2',
           ['/bin/echo', api.url.join('foo/', '/bar/', '/baz')])
  api.step('step3',
           ['/bin/echo', api.url.join('//foo/', '//bar//', '//baz//')])
  api.step('step4',
           ['/bin/echo', api.url.join('//foo/bar//', '//baz//')])


def GenTests(api):
  yield api.test('basic')
