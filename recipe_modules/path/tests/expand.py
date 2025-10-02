# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import config_types, post_process, recipe_api

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):

  def assert_raises(exc_type, func, *args, **kwargs):
    try:
      func(*args, **kwargs)
    except exc_type:
      pass
    else:
      assert False, f'{exc_type.__name__} not raised'  # pragma: no cover

  assert_raises(ValueError, api.path.expanduser, '~~')

  assert api.path.expanduser('no-tilde') == 'no-tilde'
  assert api.path.expanduser('tilde-at-end-~') == 'tilde-at-end-~'
  assert api.path.expanduser('~') == str(api.path.home_dir)
  assert api.path.expanduser('~/foo') == str(api.path.home_dir / 'foo')
  assert api.path.expanduser('~/foo/bar') == str(api.path.home_dir / 'foo/bar')

  def testexpandvars(
      variable: str,
      value: str,
      unexpanded_path: str,
      expected_path: config_types.Path,
  ) -> None:
    with api.context(env={variable: str(value)}):
      with api.step.nest(unexpanded_path):
        api.step.empty('variable').presentation.step_summary_text = variable
        value_pres = api.step.empty('value').presentation
        value_pres.step_summary_text = api.context.env[variable]

        expected_pres = api.step.empty('expected').presentation
        expected_pres.step_summary_text = str(expected_path)

        expanded = api.path.expandvars(unexpanded_path)
        expanded_pres = api.step.empty('expanded').presentation
        expanded_pres.step_summary_text = str(expanded)

        assert expanded == str(expected_path)

  foo = api.path.start_dir / 'foo'

  testexpandvars('FOO', foo, '${FOO}', foo)
  testexpandvars('FOO', foo, '${FOO}/bar', foo / 'bar')
  testexpandvars('FOO', foo, '${FOO}/bar/baz', foo / 'bar' / 'baz')

  testexpandvars('BAR', 'bar', '[START_DIR]/foo/${BAR}', foo / 'bar')

  testexpandvars('BAR', 'bar', '[START_DIR]/foo/$BAR', foo / '$BAR')


def GenTests(api):
  yield api.test('expand', api.post_process(post_process.DropExpectation))
