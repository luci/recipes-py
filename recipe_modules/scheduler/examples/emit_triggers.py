# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating emitting triggers to LUCI Scheduler."""

DEPS = [
  'json',
  'properties',
  'runtime',
  'scheduler',
  'time',
]


def RunSteps(api):
  if api.runtime.is_experimental:
    api.scheduler.set_host('https://luci-scheduler-dev.appspot.com')
  api.scheduler.emit_trigger(
      api.scheduler.buildbucket_trigger(
        properties={'some': 'none'},
        tags={'this': 'test'},
        url='https://example.com',
      ),
      project='proj',
      jobs=['job1', 'job2'],
  )

  api.scheduler.emit_triggers(
      [
        (
          api.scheduler.buildbucket_trigger(
            properties={'some': 'none'},
            tags={'this': 'test'},
          ),
          'proj',
          ['job1', 'job2']
        ),
        (
          {'id': 'id2', 'title': 'custom', 'buildbucket': {
            'properties': {'some':'one'},
            'tags': ['any=tag'],
          }},
         'proj2',
         ['job3'],
        ),
      ],
      timestamp_usec=int(api.time.time()*1e6),
      step_name='custom-batch-step',
  )


def GenTests(api):
  yield (
    api.test('basic')
    + api.runtime(is_luci=True, is_experimental=True)
    + api.properties(buildername='compiler', buildnumber='123')
    + api.step_data('luci-scheduler.EmitTriggers', stdout=api.json.output({}))
    + api.step_data('luci-scheduler.EmitTriggers', stdout=api.json.output({}))
  )
  # TODO: add failure example.
