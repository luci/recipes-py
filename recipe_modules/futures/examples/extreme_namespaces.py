# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'context',
  'futures',
  'path',
  'step',
]


def Level2(api, i):
  work = []
  with api.step.nest('Level2 [%d]' % i):
    with api.context(cwd=api.path['start_dir'].join('deep')):
      work.append(api.futures.spawn(
          api.step, 'cool step', cmd=['echo', 'cool']))

  # Specifically wait outside all the contexts; if they have a bug w.r.t. global
  # state vs. greenlet-local state, we'll see it here with bad context.
  api.futures.wait(work)


def Level1(api, i):
  with api.step.nest('Level1 [%d]' % i):
    for j in xrange(4):
      api.futures.spawn(Level2, api, j)


def RunSteps(api):
  for i in xrange(4):
    api.futures.spawn(Level1, api, i)


def GenTests(api):
  yield api.test('basic')

