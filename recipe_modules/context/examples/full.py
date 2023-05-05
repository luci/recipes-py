# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api, config

from PB.go.chromium.org.luci.lucictx.sections import Deadline

DEPS = [
  'context',
  'path',
  'raw_io',
  'step',
  'time',
]


def RunSteps(api):
  api.step('default step', ['bash', '-c', 'echo default!'])

  noop_context = {}
  with api.context(**noop_context):
    # nothing happens! this is exactly the same as above, but this optimization
    # is helpful when recipes need to calculate contextual values.
    api.step('default step', ['bash', '-c', 'echo default!'])

  # can change cwd
  api.step('mk subdir', ['mkdir', '-p', 'subdir'])
  with api.context(cwd=api.path['start_dir'].join('subdir')):
    api.step('subdir step', ['bash', '-c', 'pwd'])
    api.step('other subdir step', ['bash', '-c', 'echo hi again!'])

  # can set envvars, and path prefix.
  pants = api.path['start_dir'].join('pants')
  shirt = api.path['start_dir'].join('shirt')
  with api.context(env={'FOO': 'bar'}):
    api.step('env step', ['bash', '-c', 'echo $FOO'])

    with api.context(env_prefixes={'FOO': [pants, shirt]}):
      api.step('env step with prefix', ['bash', '-c', 'echo $FOO'])

  # Path prefix won't append empty environment variables.
  with api.context(env={'FOO': ''}, env_prefixes={'FOO': [pants, shirt]}):
    result = api.step('env prefixes with empty value',
                      ['bash', '-c', 'echo $FOO'])

  # %-formats are errors (for now). Double-% escape them.
  bad_examples = ['%format', '%s']
  for example in bad_examples:
    try:
      with api.context(env={'BAD': example}):
        assert False  # pragma: no cover
    except ValueError:
      pass

  # this is fine though:
  with api.context(env={'FINE': '%%format'}):
    pass

  # Adjusting deadlines; default is "0" deadline in tests, 30s grace period.
  # Tests display timeout==deadline.

  # low-level method
  now = api.time.time()
  with api.context(deadline=Deadline(soft_deadline=now+20, grace_period=30)):
    api.step('20 sec deadline', ['bash', '-c', 'echo default!'])

    try:
      with api.context(deadline=Deadline(soft_deadline=now+30, grace_period=30)):
        assert False  # pragma: no cover
    except ValueError:
      # cannot increase grace_period
      pass

    with api.context(deadline=Deadline(soft_deadline=now+20, grace_period=10)):
      api.step('and 10 sec grace_period', ['bash', '-c', 'echo default!'])

      try:
        with api.context(deadline=Deadline(soft_deadline=now+20, grace_period=30)):
          assert False  # pragma: no cover
      except ValueError:
        # cannot increase grace_period
        pass


def GenTests(api):
  yield api.test('basic')
