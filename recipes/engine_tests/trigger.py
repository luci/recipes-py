# Copyright (c) 2013-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
from recipe_engine.recipe_api import Property

DEPS = [
    'properties',
    'step',
]

PROPERTIES = {
    'command': Property(default=None),
}

def RunSteps(api, command):
  api.step(
      'trigger some junk',
      cmd=command,
      trigger_specs=[{
          'builder_name': 'triggered',
          'buildbot_changes': [{
              'when_timestamp': 1445412480,
          }],
      }])

def GenTests(api):
  yield api.test('basic')
