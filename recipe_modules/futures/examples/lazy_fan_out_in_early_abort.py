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
        ''' % (i+1))
      return i + 1
    futures.append(api.futures.spawn(_runner, i))

  with api.futures.iwait(futures) as iter:
    for helper in iter:
      result = helper.result()
      if result < 5:
        api.step('Sleeper %d complete' % helper.result(), cmd=None)
      else:
        result = api.step('OH NO QUIT QUIT QUIT', cmd=None)
        result.presentation.status = 'FAILURE'
        raise api.step.StepFailure('boomzors')


def GenTests(api):
  yield api.test('basic')
