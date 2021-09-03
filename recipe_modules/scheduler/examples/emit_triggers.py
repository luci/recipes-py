# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating emitting triggers to LUCI Scheduler."""

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'buildbucket',
  'json',
  'runtime',
  'scheduler',
  'time',
]


def RunSteps(api):
  if api.runtime.is_experimental:
    api.scheduler.set_host('https://luci-scheduler-dev.appspot.com')
  api.scheduler.emit_trigger(
      api.scheduler.BuildbucketTrigger(
        properties={'some': 'none'},
        tags={'this': 'test'},
        inherit_tags=False,
        url='https://example.com',
      ),
      project='proj',
      jobs=['job1', 'job2'],
  )

  api.scheduler.emit_triggers(
      [
        (
          api.scheduler.BuildbucketTrigger(
            properties={'some': 'none'},
            tags={'this': 'test'},
          ),
          'proj',
          ['job1', 'job2']
        ),
        (
         api.scheduler.GitilesTrigger(
             repo='https://chromium.googlesource.com/chromium/src',
             ref='refs/branch-heads/1235',
             revision='2d2b87e5f9c872902d8508f6377470a4a6fa87e1',
             title='advanced gitiles trigger'
         ),
         'proj3',
         ['job1'],
        ),
      ],
      timestamp_usec=int(api.time.time()*1e6),
      step_name='custom-batch-step',
  )


def GenTests(api):
  yield (
    api.test('basic')
    + api.runtime(is_experimental=True)
    + api.buildbucket.ci_build(builder='compiler', build_number=123)
    + api.step_data('luci-scheduler.EmitTriggers', stdout=api.json.output({}))
    + api.step_data('luci-scheduler.EmitTriggers', stdout=api.json.output({}))
  )
  # TODO: add failure example.
