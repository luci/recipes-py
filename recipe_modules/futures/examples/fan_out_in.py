# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'futures',
  'python',
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
        '''
    ))

  assert len(api.futures.wait(futures)) == 10, "All done"


def GenTests(api):
  yield api.test('basic')
