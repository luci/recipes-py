# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine.post_process import DropExpectation

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
  api.generator_script(script_name)

def GenTests(api):
  yield api.test(
      'basic',
      api.properties(script_name="bogus"),
      api.generator_script(
          'bogus',
          {'name': 'mock.step.binary', 'cmd': ['echo', 'mock step binary']}
      ),
      api.post_check(lambda check, steps: check(
          'bogus' in steps['gen step(bogus)'].cmd
      )),
      api.post_check(lambda check, steps: check(
          'echo' in steps['mock.step.binary'].cmd
      )),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'basic_python',
      api.properties(script_name="bogus.py"),
      api.generator_script(
          'bogus.py',
          {'name': 'mock.step.python', 'cmd': ['echo', 'mock step python']},
      ),
      api.post_check(lambda check, steps: check(
          ['vpython3', ..., 'bogus.py'] in steps['gen step(bogus.py)'].cmd
      )),
      api.post_check(lambda check, steps: check(
          'echo' in steps['mock.step.python'].cmd
      )),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'presentation',
      api.properties(script_name='presentation.py'),
      api.generator_script(
          'presentation.py', {
            'name': 'mock.step.presentation',
            'cmd': ['echo', 'mock step presentation'],
            'outputs_presentation_json': True
          }
      ),
      api.step_data(
          'mock.step.presentation',
          api.json.output({'step_text': 'mock step text'})
      ),
      api.post_check(lambda check, steps: check(
          steps['mock.step.presentation'].step_text == 'mock step text'
      )),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'always_run',
      api.properties(script_name='always_run.py'),
      api.generator_script(
          'always_run.py',
          {'name': 'runs', 'cmd': ['echo', 'runs succeeds']},
          {'name': 'fails', 'cmd': ['echo', 'fails fails!']},
          {'name': 'skipped', 'cmd': ['echo', 'absent']},
          {'name': 'always_runs', 'cmd': ['echo', 'runs anyway'],
           'always_run': True},
      ),
      api.step_data('fails', retcode=1),
      api.post_check(lambda check, steps: check(
          ['echo', 'runs anyway'] in steps['always_runs'].cmd
      )),
      api.expect_status('FAILURE'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'malformed_list',
      api.properties(script_name='not_list.py'),
      api.step_data(
          'gen step(not_list.py)',
          api.json.output({'not': 'a list'})),
      api.post_check(lambda check, steps: check(
          steps['gen step(not_list.py)'].status == 'EXCEPTION'
      )),
      api.expect_status('FAILURE'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'malformed_command',
      api.properties(script_name='malformed.py'),
      api.generator_script(
          'malformed.py',
          {'name': 'run', 'cmd': ['echo', 'there are', 4, 'cows']}),
      api.post_check(lambda check, steps: check(
          steps['gen step(malformed.py)'].status == 'EXCEPTION'
      )),
      api.expect_status('FAILURE'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'missing_name',
      api.properties(script_name='missing_name.py'),
      api.generator_script(
          'missing_name.py',
          {'cmd': ['echo', 'hey']}),
      api.post_check(lambda check, steps: check(
          steps['gen step(missing_name.py)'].status == 'EXCEPTION'
      )),
      api.expect_status('FAILURE'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'bad_key',
      api.properties(script_name='bad_key.py'),
      api.generator_script(
          'bad_key.py',
          {'name': 'whatever', 'bad': 'key'}),
      api.post_check(lambda check, steps: check(
          steps['gen step(bad_key.py)'].status == 'EXCEPTION'
      )),
      api.expect_status('FAILURE'),
      api.post_process(DropExpectation),
  )
