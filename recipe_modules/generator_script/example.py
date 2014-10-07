# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'generator_script',
  'json',
  'path',
  'properties',
  'step',
]


def GenSteps(api):
  api.path['checkout'] = api.path['slave_build']
  script_name = api.properties['script_name']
  script_env = api.properties.get('script_env')
  api.generator_script(script_name, env=script_env)

def GenTests(api):
  yield (
    api.test('basic') +
    api.properties(script_name="bogus") +
    api.generator_script(
      'bogus',
      {'name': 'mock.step.binary', 'cmd': ['echo', 'mock step binary']}
    )
  )

  yield (
    api.test('basic_python') +
    api.properties(script_name="bogus.py", script_env={'FOO': 'bar'}) +
    api.generator_script(
      'bogus.py',
      {'name': 'mock.step.python', 'cmd': ['echo', 'mock step python']},
    )
  )

  yield (
    api.test('presentation') +
    api.properties(script_name='presentation.py') +
    api.generator_script(
      'presentation.py', {
        'name': 'mock.step.presentation',
        'cmd': ['echo', 'mock step presentation'],
        'outputs_presentation_json': True
      }
    ) +
    api.step_data(
      'mock.step.presentation',
      api.json.output({'step_text': 'mock step text'})
    )
  )

  yield (
    api.test('always_run') +
    api.properties(script_name='always_run.py') +
    api.generator_script(
      'always_run.py',
      {'name': 'runs', 'cmd': ['echo', 'runs succeeds']},
      {'name': 'fails', 'cmd': ['echo', 'fails fails!']},
      {'name': 'skipped', 'cmd': ['echo', 'absent']},
      {'name': 'always_runs', 'cmd': ['echo', 'runs anyway'],
       'always_run': True},
    ) +
    api.step_data('fails', retcode=1)
  )
