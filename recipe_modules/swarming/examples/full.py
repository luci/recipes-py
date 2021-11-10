# -*- coding: utf-8 -*-
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.utils import iteritems

import difflib

from recipe_engine.post_process import DropExpectation
from recipe_engine.recipe_api import Property

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


DEPS = [
    'cipd',
    'json',
    'path',
    'properties',
    'step',
    'swarming',
]

EXECUTION_TIMEOUT_SECS = 3600


def RunSteps(api):
  api.swarming.ensure_client()

  # Create a new Swarming task request.
  request = (api.swarming.task_request().
      with_name('recipes-go').
      with_priority(100).
      with_service_account('account@example.iam.gserviceaccount.com').
      with_realm('chromium:ci').
      with_resultdb())

  ensure_file = api.cipd.EnsureFile()
  ensure_file.add_package('infra/git/${platform}', 'version:2.14.1.chromium10')

  # Configure the first slice.
  request = (request.with_slice(0, request[0].
        with_command(['recipes', 'run', '"example"']).
        with_relative_cwd('some/subdir').
        with_dimensions(pool='example.pool', os='Debian').
        with_cipd_ensure_file(ensure_file).
        with_env_vars(SOME_VARNAME='stuff', GOPATH='$HOME/go').
        with_env_prefixes(PATH=["path/to/bin/dir", "path/to/other/bin/dir"]).
        with_expiration_secs(3600).
        with_wait_for_capacity(True).
        with_io_timeout_secs(600).
        with_execution_timeout_secs(EXECUTION_TIMEOUT_SECS).
        with_idempotent(True).
        with_containment_type('AUTO').
        with_named_caches({'cache_name': 'cache/path'}),
      )
  )

  request = request.with_slice(
      0, request[0].with_cas_input_root(
          '24b2420bc49d8b8fdc1d011a163708927532b37dc9f91d7d8d6877e3a86559ca/73')
  )

  # Check a request with no tags and no user can make it to JSON and back.
  # These requests should be considered valid.
  req_no_tag_no_user_jsonish = request.to_jsonish()
  api.swarming.task_request_from_jsonish(req_no_tag_no_user_jsonish)

  # Add user and tags for coverage of those.
  request = request.with_user('defaultuser').with_tags(
      {'key': ['value1', 'value2']})

  # Append a slice that is a variation of the last one as a starting point.
  request = request.add_slice(request[-1].with_grace_period_secs(
      20).with_secret_bytes(b'shh, don\'t tell').with_outputs(
          ['my/output/file']))

  # There should be three task slices at this point.
  assert len(request) == 2

  # Assert from_josnish(x.to_jonish()) == x
  jsonish = request.to_jsonish()
  from_jsonish = api.swarming.task_request_from_jsonish(jsonish)
  back_to_jsonish = from_jsonish.to_jsonish()
  diff = list(difflib.unified_diff(
      api.json.dumps(jsonish, indent=2).splitlines(),
      api.json.dumps(back_to_jsonish, indent=2).splitlines()))
  assert not diff, ''.join(diff)

  # Dimensions, and environment variables and prefixes can be unset.
  slice = request[-1]
  assert slice.dimensions == {'pool': 'example.pool', 'os': 'Debian'}
  assert slice.env_vars == {'SOME_VARNAME': 'stuff', 'GOPATH': '$HOME/go'}
  assert (slice.env_prefixes ==
          {'PATH' : ["path/to/bin/dir", "path/to/other/bin/dir"]})

  slice = (slice.
    with_dimensions(os=None).
    with_env_vars(GOPATH=None).
    with_env_prefixes(PATH=None)
  )

  assert slice.dimensions == {'pool': 'example.pool'}
  assert slice.env_vars == {'SOME_VARNAME': 'stuff'}
  assert slice.env_prefixes == {}

  # Setting environment prefixes is additive.
  slice = slice.with_env_prefixes(PATH=['a']).with_env_prefixes(PATH=['b'])
  assert slice.env_prefixes == {'PATH': ['a', 'b']}

  # Trigger the task request.
  metadata = api.swarming.trigger('trigger 1 task', requests=[request])

  # From the request metadata, one can access the task's name, id, and
  # associated UI link.
  assert len(metadata) == 1
  metadata[0].name
  metadata[0].id
  metadata[0].task_ui_link
  metadata[0].invocation

  # Collect the result of the task by metadata.
  output_dir = api.path.mkdtemp('swarming')
  results = api.swarming.collect('collect', metadata, output_dir=output_dir,
                                 timeout='5m', verbose=True)
  # Or collect by by id.
  results += api.swarming.collect('collect other pending task', ['0'],
                                  eager=True)

  results[0].name
  results[0].id
  results[0].state
  results[0].success
  results[0].output
  results[0].outputs
  results[0].output_dir
  results[0].duration_secs
  results[0].bot_id
  results[0].raw

  # Raise an error if something went wrong.
  if not results[0].success:
    threw = False
    try:
      results[0].analyze()
    except api.step.StepFailure as e:
      threw = True
      s = str(e)
      if results[0].state == api.swarming.TaskState.BOT_DIED:
        assert s == 'The bot running this task died', repr(s)
      elif results[0].state == api.swarming.TaskState.CANCELED:
        assert s == 'The task was canceled before it could run', repr(s)
      elif results[0].state == api.swarming.TaskState.COMPLETED:
        out = '(…)' + 'A' * 996
        assert s in ('Swarming task failed:\n' + out,
                     'Swarming task failed:\nNone'), repr(s)
      elif results[0].state == api.swarming.TaskState.EXPIRED:
        assert s == 'Timed out waiting for a bot to run on', repr(s)
      elif results[0].state == api.swarming.TaskState.KILLED:
        assert s == 'The task was killed mid-execution', repr(s)
      elif results[0].state == api.swarming.TaskState.NO_RESOURCE:
        assert s == 'Found no bots to run this task', repr(s)
      elif results[0].state == api.swarming.TaskState.TIMED_OUT:
        out = '(…)' + '\nDying' * 166
        expected = [
            'Timed out after 3599 seconds.\nOutput:\n' + out,
            'Execution timeout: exceeded 3600 seconds.\nOutput:\nhello world!',
            'I/O timeout: exceeded 600 seconds.\nOutput:\nhello world!',
        ]
        assert s in expected, repr(s)
      elif results[0].state is None:
        assert (
            s == 'Failed to collect:\nBot could not be contacted'), repr(s)
      else:  # pragma: no cover
        raise AssertionError('unexpected state: %r\n%r' % (results[0].state, s))
    except Exception as e:  # pragma: no cover
      raise AssertionError('wrong exception raised: %r' % e)
    if not threw:  # pragma: no cover
      raise AssertionError('exception was not raised')
  else:
    results[0].analyze()

  with api.swarming.on_path():
    api.step('some step with swarming on path', [])

  # verify swarming server correctly reverts
  api.swarming.trigger(
      'trigger on original server', requests=[request], verbose=True)
  api.swarming.collect('collect on original server', ['0'])


def GenTests(api):
  # For coverage
  api.swarming.example_task_request_jsonish()

  yield api.test('basic')

  states = {state.name : api.swarming.TaskState[state.name]
            for state in api.swarming.TaskState if state not in [
              api.swarming.TaskState.INVALID,
              api.swarming.TaskState.PENDING,
              api.swarming.TaskState.RUNNING,
              api.swarming.TaskState.TIMED_OUT,
            ]}
  states['unreachable'] = None

  for name, value in iteritems(states):

    result = api.swarming.task_result(
      id='0', name='recipes-go', state=value, outputs=('out.tar'),
    )
    yield (api.test('collect_with_state_%s' % name) +
      api.override_step_data('collect', api.swarming.collect([result]))
    )

  timeout_result = api.swarming.task_result(
      id='100', name='recipes-go', duration=EXECUTION_TIMEOUT_SECS - 1,
      state=api.swarming.TaskState.TIMED_OUT,
      output='Dying\n' * 500,
  )
  yield (api.test('collect_with_state_TIMED_OUT') +
    api.override_step_data('collect', api.swarming.collect([timeout_result]))
  )

  io_timeout_result = api.swarming.task_result(
      id='0', name='recipes-go', duration=EXECUTION_TIMEOUT_SECS - 1,
      state=api.swarming.TaskState.TIMED_OUT,
  )
  yield (api.test('collect_with_state_TIMED_OUT_by_io') +
    api.override_step_data('collect', api.swarming.collect([io_timeout_result]))
  )

  execution_timeout_result = api.swarming.task_result(
      id='0', name='recipes-go', duration=EXECUTION_TIMEOUT_SECS + 1,
      state=api.swarming.TaskState.TIMED_OUT,
  )
  yield (api.test('collect_with_state_TIMED_OUT_by_execution') +
    api.override_step_data(
      'collect', api.swarming.collect([execution_timeout_result]))
  )

  failed_result = api.swarming.task_result(
      id='0', name='recipes-go', state=api.swarming.TaskState.COMPLETED,
      failure=True, outputs=('out.tar'),
      output='AAA'*500,
  )
  yield (api.test('collect_with_state_COMPLETED_and_failed') +
    api.override_step_data('collect', api.swarming.collect([failed_result]))
  )

  no_output_result = api.swarming.task_result(
      id='0',
      name='recipes-go',
      state=api.swarming.TaskState.COMPLETED,
      failure=True,
      output=None,
  )
  yield (api.test('collect_with_no_output') + api.override_step_data(
      'collect', api.swarming.collect([no_output_result])) +
         api.post_process(DropExpectation))

  yield (api.test('check_triggered_request') + api.post_check(
      api.swarming.check_triggered_request,
      'trigger 1 task', lambda check, request: check(request[0].dimensions == {
          'os': 'Debian',
          'pool': 'example.pool'
      }), lambda check, request: check(request[0].env_vars[
          'SOME_VARNAME'] == 'stuff'), lambda check, request: check(request[
              0].wait_for_capacity)) + api.post_process(DropExpectation))
