# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'generator_script',
    'json',
    'path',
    'properties',
    'step',
]

PROPERTIES = {
    'script_name': Property(kind=str),
}

def RunSteps(api, script_name):
  api.path['checkout'] = api.path['tmp_base']
  script_name = api.properties['script_name']
  api.generator_script(script_name, interpreter='vpython3')

def GenTests(api):
  yield (
      api.test('vpython3') +
      api.properties(script_name="bogus.py") +
      api.generator_script(
          'bogus.py',
          {'name': 'mock.vpython3', 'cmd': ['echo', 'mock step binary']}
      )
  )