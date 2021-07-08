# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'isolated',
]


def RunSteps(api):
  # Inspect the associated isolated server.
  api.isolated.isolate_server
  api.isolated.namespace


def GenTests(api):
  yield api.test('basic')
  yield (api.test('override isolated') +
         api.isolated.properties(server='bananas.example.com'))
