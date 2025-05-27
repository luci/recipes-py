# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This recipe tests the buildbucket.set_output_gitiles_commit function."""

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
  'buildbucket',
  'platform',
  'properties',
  'raw_io',
  'step',
]


def RunSteps(api):
  api.buildbucket.set_output_gitiles_commit(
    common_pb2.GitilesCommit(
        host='chromium.googlesource.com',
        project='infra/infra',
        ref='refs/heads/main',
        id='a' * 40,
        position=42,
    ),
  )


def GenTests(api):
  yield api.test('basic')

