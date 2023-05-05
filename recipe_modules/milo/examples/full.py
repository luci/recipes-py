# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'milo',
]

def RunSteps(api):
  api.milo.show_blamelist_for([
    # Test proto format.
    common_pb2.GitilesCommit(
        host='chromium.googlesource.com',
        project='chromium/src',
        id='51634e6bffd3c4f521645a40c721430721153711',
    ),
    # Test dict format.
    {
        'host': 'chromium.googlesource.com',
        'project': 'angle/angle',
        'id': 'e196bc85ac2dda0e9f6664cfc2eca0029e33d2d1',
    }
  ])

def GenTests(api):
  yield api.test('basic')
