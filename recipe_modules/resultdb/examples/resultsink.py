# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import (DropExpectation, StepCommandContains,
  DoesNotRunRE)

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import invocation as invocation_pb2

DEPS = [
  'buildbucket',
  'resultdb',
  'step',
]


def RunSteps(api):
  api.step('test', api.resultdb.wrap(['echo', 'suppose its a test']))


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(),
  )
