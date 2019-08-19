# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class LedTestApi(recipe_test_api.RecipeTestApi):
  def get_builder(self, api, *args, **kwargs):
    """Entrypoint for mocking a series of piped led calls.

    It stores the initial `led get-builder` data in a `LedTestData` object
    and makes incremental modifications to that data as the methods
    corresponding to led commands are called. At the same time, it mocks the
    output of those commands for testing purposes. This allows tests using
    the led recipe module to mock a whole series of led commands piped
    together that make modifications to the same base build/builder data.

    Note that the mock build/builder JSON contained by a `LedTestData` object
    (and reflected in the expectation files) does not actually conform to the
    schema used by led. This is intentional, as that schema is an internal
    detail of led that recipes should not depend on. `led launch` is the only
    command whose stdout is suitable for consumption by recipes.

    Retrieve the `step_data` attribute at the end of a chain of method calls
    to return the `TestData` object corresponding to the mocked chain of
    commands.

    For example, to mock the output of the chain of commands:
      led get-builder ... | led edit -rbh somehash | led launch
    start with the following test case:

      yield (
        api.test('led-basics') +
        api.led.get_builder(api)
               .edit_input_recipes(isolated_hash='somehash')
               .launch()
               .step_data
      )
    """
    return LedTestData(api).get_builder(*args, **kwargs)


class LedTestData(object):
  def __init__(self, api):
    self._api = api
    self._led_data = {}
    self._step_data = None

  @property
  def step_data(self):
    """The corresponding TestData object.

    led commands corresponding to the methods called on this object will be
    faked.
    """
    return self._step_data

  def get_builder(self, name='led get-builder'):
    """Mocks a call to `led get-builder`."""
    self._led_data = {
        'builder_name': 'some-builder',
        'recipe_properties': {},
    }
    return self._add_step_data(name)

  def edit_input_recipes(self, name='led edit', isolated_hash=None,
                         cipd_source=None):
    """Mocks a call to `led edit` (e.g. via `api.led.inject_input_recipes`)
    that modifies the input recipes.
    """
    assert bool(isolated_hash) != bool(cipd_source), (
        'exactly one of isolated_input and cipd_input must be set')

    if isolated_hash:
      self._led_data['recipe_isolated_hash'] = isolated_hash
    if cipd_source:
      self._led_data['recipe_cipd_source'] = cipd_source

    return self._add_step_data(name)

  def edit_properties(self, name='led edit', **properties):
    """Mocks a call to `led edit` that modifies the input properties."""
    self._led_data['recipe_properties'].update(properties)
    return self._add_step_data(name)

  def launch(self, name='led launch'):
    """Mocks a call to `led launch`."""
    launch_data = {
        'swarming': {
            'host_name': 'chromium-swarm.appspot.com',
            'task_id': 'deadbeeeeef',
        }
    }
    return self._add_step_data(name, launch_data)

  def _add_step_data(self, name, led_data=None):
    if led_data is None:
      led_data = self._led_data
    step_data = self._api.step_data(
        name, stdout=self._api.json.output(led_data))
    if self._step_data is None:
      self._step_data = step_data
    else:
      self._step_data += step_data
    return self
