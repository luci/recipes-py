# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Simple recipe which runs a bunch of subprocesses which react to early
termination in different ways."""

DEPS = [
  'file',
  'futures',
  'path',
  'platform',
  'step',
]

from PB.recipes.recipe_engine.engine_tests import early_termination

PROPERTIES = early_termination.InputProperties


def RunSteps(api, props):
  work = []

  output_touchfile = props.output_touchfile
  if not output_touchfile:
    output_touchfile = api.path.cleanup_dir.joinpath('output_touchfile')
  running_touchfile = props.running_touchfile
  if not running_touchfile:
    running_touchfile = api.path.cleanup_dir.joinpath('running_touchfile')
  # make sure touchfile is there
  api.file.write_text("ensure output_touchfile", output_touchfile,
                      "meep".encode('utf-8'))

  # note that our helper script
  #  * Looks for the output touchfile as the first arg
  #  * Looks for `--always-ignore` or `--no-handler` somewhere in argv
  #  * Ignores everything else.
  #
  # We add the step name at the end of the command so that when debugging this
  # locally it's easy to tell which processes are which with e.g. `pstree`.

  # This one tries its darndest to stay alive
  work.append(
      api.futures.spawn_immediate(api.step, 'ignore always', [
          'python3',
          api.resource('sleepytime.py'), output_touchfile, '--always-ignore',
          'ignore always'
      ]))

  # This one nicely quits on TERM
  work.append(
      api.futures.spawn_immediate(api.step, 'nice shutdown', [
          'python3',
          api.resource('sleepytime.py'), output_touchfile, 'nice shutdown'
      ]))

  # This one is self-timed-out
  work.append(
      api.futures.spawn_immediate(
          api.step,
          'self timeout', [
              'python3',
              api.resource('sleepytime.py'), output_touchfile,
              '--always-ignore', 'self timeout'
          ],
          timeout=5))

  def _pure_sleep():
    # This one is totally oblivious
    try:
      api.step('sleep', [
          'python3',
          api.resource('sleepytime.py'), output_touchfile, '--no-handler',
          'sleep'
      ])
    except Exception:  # pragma: no cover
      # BAD! don't do bare exceptions... however...
      api.step('no run', None).presentation.step_text = "I don't run"
  work.append(api.futures.spawn_immediate(_pure_sleep))

  # all greenlets running, write our running file
  api.file.write_text("ensure running_touchfile", running_touchfile,
                      "meep".encode('utf-8'))

  for w in work:
    w.exception()  # mark exception as handled.


def GenTests(api):
  yield api.test('basic')
