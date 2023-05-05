# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from contextlib import contextmanager

DEPS = [
  'futures',
  'json',
  'path',
  'raw_io',
  'step',
]


HELPER_TIMEOUT = object()


def manage_helper(api, chn):
  with api.step.nest('helper'):
    pid_file = api.path['cleanup'].join('pid_file')
    helper_future = api.futures.spawn_immediate(
        api.step, 'helper loop',
        ['python', api.resource('helper.py'), pid_file],
        cost=None, # always run this background thread.
        __name='background process',
    )
    try:
      proc_data = api.step(
          'wait for it', [
            'python',
            api.resource('wait_for_helper.py'),
            pid_file,
            api.json.output(),
          ],
          timeout=30,
          cost=None, # always run the checker.
      ).json.output
      # show it as terminated immediately; otherwise this will show as running
      # until we exit the 'helper' nest context, due to the current recipe
      # engine semanics around step closure.
      api.step.close_non_nest_step()
    except api.step.StepFailure:
      helper_future.cancel()
      helper_future.result()
      chn.put(HELPER_TIMEOUT)
      return

    chn.put(proc_data)  # or whatever data you want to expose to the user.

    # Now we wait on the channel to see when to shut down.
    chn.get()

    helper_future.cancel()
    helper_future.result()


@contextmanager
def run_helper(api):
  """Runs the background helper.

  Yields control once helper is ready. Kills helper once leaving the context
  manager.

  This is an example of what your recipe module code would look like. Note that
  we don't pass the channel to the 'user' code (i.e. RunSteps).
  """
  management_channel = api.futures.make_channel()
  helper_manager = None
  try:
    helper_manager = api.futures.spawn(
        manage_helper, api, management_channel, __name='background manager')
    # block until the helper is ready.
    if management_channel.get() is HELPER_TIMEOUT:
      # This timed out, so the helper_manager won't be listening to
      # management_channel any more, so null it out.
      helper_manager = None
      raise api.step.StepFailure('timed out while waiting for helper')
    yield  # maybe yield some connection info, or a client object, or whatever.
  finally:
    if helper_manager:
      management_channel.put(None)


def RunSteps(api):
  with run_helper(api):
    api.step(
        'do something with live helper',
        ['python3', '-u', api.resource('do_something.py')])


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('helper.wait for it', api.json.output({
        'pid': 12345,
      })),
  )

  yield api.test(
      'wait times out',
      api.step_data('helper.wait for it', times_out_after=100),
      status='FAILURE',
  )
