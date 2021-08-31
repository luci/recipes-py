# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'context',
  'futures',
  'step',
]

def RunSteps(api):
  # We want to make sure that context is kept per-greenlet.

  chan = api.futures.make_channel()
  with api.context(infra_steps=True):
    assert api.context.infra_step

    def _assert_still_true():
      chan.get()  # wait until we're totally out of the context
      assert api.context.infra_step

    future = api.futures.spawn(_assert_still_true)

  chan.put(None)
  future.result()

  api.step('we made it', ['echo', 'woot'])


def GenTests(api):
  yield api.test('basic')
