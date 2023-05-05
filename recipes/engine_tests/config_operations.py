# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that recipes can modify configuration options in various ways."""
from past.builtins import basestring

# This code is typically located inside a module/config.py file, but we inline
# it here for the testing purposes.
from recipe_engine.config import (
    config_item_context, ConfigGroup, ConfigList, Dict, List, Single, Static)

def BaseConfig(**_kwargs):
  return ConfigGroup(
    # Various config options to be exercised in tests.
    thedict    = Dict(value_type=tuple),
    thelist    = List(basestring),
    thestring  = Single(basestring, required=True),
    thebool    = Single(bool, required=False, empty_val=False),
    thesubconfig  = ConfigGroup(
      thefloat = Single(float),
      thestaticint = Static(42, hidden=False),
    ),
  )

config_ctx = config_item_context(BaseConfig)

@config_ctx()
def test1(c): # pragma: no cover
  c.thedict['a'] = (1, 2)

@config_ctx()
def test2a(c): # pragma: no cover
  c.thelist.append('foo')

@config_ctx(includes=['test2a'])
def test2(c): # pragma: no cover
  c.thestring = 'foobar'


# This is where the actual recipe code begins.
DEPS = [
  'step',
  'json',
]

def DumpRecipeEngineTestConfig(api, config):
  api.step('config', cmd=None).presentation.logs['config'] = api.json.dumps(
      config.as_jsonish(), indent=2).splitlines()


def RunSteps(api):
  config = test1()        # api.module.set_config('test1')
  config = test2(config)  # api.module.apply_config('test2')

  DumpRecipeEngineTestConfig(api, config)

  config.thelist.append('bar')
  config.thelist.extend(['baz'])
  config.thelist.remove('bar')

  DumpRecipeEngineTestConfig(api, config)

  config.thedict['b'] = ('bar', 'baz')
  del config.thedict['a']

  DumpRecipeEngineTestConfig(api, config)

  config.thebool = True
  config.thestring = 'cookoo'
  config.thesubconfig.thefloat = float(
      config.thesubconfig.thestaticint)

  DumpRecipeEngineTestConfig(api, config)


def GenTests(api):
  yield api.test('basic')
