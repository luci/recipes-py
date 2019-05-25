# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api, config

DEPS = [
  'context',
  'path',
  'raw_io',
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

  # Don't use | in namespaces or name prefixes
  try:
    with api.context(namespace="dope|pipe"):
      assert False  # pragma: no cover
  except ValueError:
    pass
  try:
    with api.context(name_prefix="nope|pipe"):
      assert False  # pragma: no cover
  except ValueError:
    pass

  # this is fine though:
  with api.context(env={'FINE': '%%format'}):
    pass

  # can increment namespace. However, if you use `api.step.nest` it gives you
  # the step result to manipulate.
  # YES:
  with api.step.nest('nested') as nest:
    api.step('properly indented', ['bash', '-c', 'echo yay!'])
    nest.status = 'FAILURE'
  # As opposed to:
  with api.context(namespace='something'):
    api.step('indented but no step', ['bash', '-c', 'echo y u do?'])

  # Can also adjust name_prefix within the current namespace:
  with api.context(namespace='neat namespace'):
    with api.context(name_prefix='information: '):
      api.step('informed', ['bash', '-c', 'echo yay!'])

      with api.context(namespace='secret'):
        api.step('informed secret!', ['bash', '-c', 'echo yay!'])

    with api.context(namespace='deep', name_prefix='sturdy: '):
      api.step('mines of moria', ['bash', '-c', 'echo yay!'])

    api.step('regular', ['bash', '-c', 'echo yay!'])


def GenTests(api):
  yield api.test('basic')
