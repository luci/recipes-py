# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'nodejs',
    'platform',
    'step',
]


def RunSteps(api):
  with api.nodejs(version='17.9.9'):
    api.step('npm', ['npm', 'version'])
  with api.nodejs(version='18.0.0'):
    api.step('npm', ['npm', 'version'])
  with api.nodejs(version='18.0.666'):
    api.step('npm', ['npm', 'version'])
  with api.nodejs(version='23.0.0'):
    api.step('npm', ['npm', 'version'])


def GenTests(api):
  for platform in ('linux', 'mac', 'win'):
    yield (
        api.test(platform) +
        api.platform.name(platform))
