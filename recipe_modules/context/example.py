# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api, config

DEPS = [
  'context',
  'path',
  'step',
]


def RunSteps(api):
  api.step('default step', ['bash', '-c', 'echo default!'])

  noop_context = {}
  with api.context(**noop_context):
    # nothing happens! this is exactly the same as above, but this optimization
    # is helpful when recipes need to calculate contextual values.
    api.step('default step', ['bash', '-c', 'echo default!'])

  # can change cwd
  api.step('mk subdir', ['mkdir', 'subdir'])
  with api.context(cwd=api.path['start_dir'].join('subdir')):
    api.step('subdir step', ['bash', '-c', 'pwd'])
    api.step('other subdir step', ['bash', '-c', 'echo hi again!'])

  # can set envvars
  with api.context(env={"HELLO": "WORLD", "HOME": None}):
    api.step('env step', ['bash', '-c', 'echo $HELLO; echo $HOME'])

  # can increment nest level... note that this is a low level api, prefer
  # api.step.nest instead:
  # YES:
  with api.step.nest('nested'):
    api.step('properly indented', ['bash', '-c', 'echo yay!'])
  # AVOID:
  with api.context(increment_nest_level=True):
    api.step('indented with wrong name', ['bash', '-c', 'echo indent?'])


def GenTests(api):
  yield api.test('basic')
