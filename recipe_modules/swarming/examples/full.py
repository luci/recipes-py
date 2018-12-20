# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property


DEPS = [
  'cipd',
  'runtime',
  'step',
  'swarming',
]


def RunSteps(api):
  # Create a new Swarming task request.
  request = (api.swarming.task_request().
      with_name('recipes-go').
      with_priority(100).
      with_service_account("account@example.iam.gserviceaccount.com")
  )

  ensure_file = api.cipd.EnsureFile()
  ensure_file.add_package('infra/git/${platform}', 'version:2.14.1.chromium10')

  # Configure the first slice.
  request = (request.with_slice(0, request[0].
        with_command(['recipes', 'run', '"example"']).
        with_dimensions(pool='example.pool', os='Debian').
        with_cipd_ensure_file(ensure_file).
        with_isolated('606d94add94223636ee516c6bc9918f937823ccc').
        with_expiration_secs(3600).
        with_io_timeout_secs(600).
        with_hard_timeout_secs(3600).
        with_idempotent(True),
      )
  )

  # Append a slice that is a variation of the last one as a starting point.
  request = request.add_slice(request[-1].
    with_grace_period_secs(20).
    with_secret_bytes('shh, don\'t tell'),
  )

  # Dimensions can be unset.
  slice = request[-1]
  assert cmp(slice.dimensions, {'pool': 'example.pool', 'os': 'Debian'}) == 0

  slice = slice.with_dimensions(os=None)
  assert cmp(slice.dimensions, {'pool': 'example.pool'}) == 0

  # There should be two task slices at this point.
  assert len(request) == 2

  # Trigger the task request.
  metadata = api.swarming.trigger(requests=[request])

  # From the request metadata, one can access the task's name, id, and
  # associated UI link.
  assert len(metadata) == 1
  metadata[0].name
  metadata[0].id
  metadata[0].task_ui_link

  with api.swarming.on_path():
    api.step('some step with swarming on path', [])


def GenTests(api):
  yield api.test('basic')
  yield api.test('experimental') + api.runtime(is_luci=False, is_experimental=True)
  yield (api.test('override swarming') +
    api.swarming.properties(server='bananas.example.com', version='release')
  )
