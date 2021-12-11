# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'futures',
  'python',
  'step',
]


def worker(api, sem, i, N):
  with api.step.nest('worker %d' % i):
    with sem:
      api.step('serialized work', ['python3', api.resource('sleep.py'), 5])
    api.step('parallel work', ['python3', api.resource('sleep.py'), 5*N])


def RunSteps(api):
  futures = []
  sem = api.futures.make_bounded_semaphore()
  # total time should be (5s * N) * 2
  N = 10
  for i in range(N):
    futures.append(api.futures.spawn(worker, api, sem, i, N, __meta=i))

  for fut in api.futures.iwait(futures):
    api.step('Sleeper %d complete' % fut.meta, cmd=None)


def GenTests(api):
  yield api.test('basic')
