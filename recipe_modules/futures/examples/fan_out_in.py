# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'futures',
  'python',
  'step',
]


def RunSteps(api):
  futures = []
  for _ in xrange(10):
    futures.append(api.futures.spawn(
        api.python.inline,
        'sleep loop',
        '''
          import time
          for x in xrange(30):
            print "Hi! %s" % x
            time.sleep(1)
        ''',
        cost=api.step.ResourceCost(cpu=2*api.step.CPU_CORE),
    ))

  assert len(api.futures.wait(futures)) == 10, "All done"


def GenTests(api):
  yield (
    api.test('basic')
    + api.post_check(lambda check, steps: check(
        steps['sleep loop'].cost.cpu == 2000
    ))
  )
