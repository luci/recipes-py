# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
  'buildbucket',
  'resultdb',
  'step',
]


def RunSteps(api):
  api.step('host', [api.resultdb.host])


def GenTests(api):
  yield api.test('basic')

  yield (
    api.test('custom host') +
    api.buildbucket.build(build_pb2.Build(
      infra=dict(resultdb=dict(hostname='custom.results.api.cr.dev'))
    ))
  )
