# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'futures',
  'python',
  'step',
]


def RunSteps(api):
  futures = []
  for i in range(10):
    def _runner(i):
      api.python.inline(
        'sleep loop [%d]' % (i+1),
        '''
          import time
          for x in range(%d):
            print("Hi! %%s" %% x)
            time.sleep(1)
        ''' % (i+1), cost=api.step.ResourceCost())
      return i + 1
    futures.append(api.futures.spawn(_runner, i))

  for helper in api.futures.iwait(futures):
    api.step('Sleeper %d complete' % helper.result(), cmd=None)


def GenTests(api):
  yield api.test('basic')
