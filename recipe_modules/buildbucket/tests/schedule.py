# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import types

DEPS = [
  'buildbucket',
  'properties',
  'runtime',
  'step'
]


def RunSteps(api):
  # Convert from FrozenDict
  req_body = types.thaw(api.properties.get('request_kwargs'))
  req = api.buildbucket.schedule_request(**req_body)
  api.buildbucket.schedule([req])

  api.buildbucket.run([req])


def GenTests(api):

  def test(test_name, response=None, **req):
    req.setdefault('builder', 'linux')
    return (
      api.test(test_name) +
      api.runtime(is_luci=True, is_experimental=False) +
      api.buildbucket.try_build(
          project='chromium',
          builder='Builder',
          git_repo='https://chromium.googlesource.com/chromium/src',
          revision='a' * 40,
          build_sets={'bs'},
      ) +
      api.properties(request_kwargs=req, response=response)
    )

  yield test('basic')

  yield test(
      test_name='tags',
      tags=[{'key': 'a', 'value': 'b'}]
  )

  yield test(
      test_name='dimensions',
      dimensions=[{'key': 'os', 'value': 'Windows'}]
  )

  yield test(
      test_name='properties',
      properties={
          'str': 'b',
          'obj': {
              'p': 1,
          },
      }
  )

  yield test(
      test_name='experimental',
      experimental=True,
  )

  yield test(
      test_name='non-experimental',
      experimental=False,
  )

  err_batch_res = dict(
      responses=[
        dict(
            error=dict(
                code=1,
                message='bad',
            ),
        ),
      ],
  )
  yield (
      test(test_name='error') +
      api.buildbucket.simulated_schedule_output(err_batch_res)
  )
