# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections

from slave.recipe_config import List
from slave.recipe_config import (config_item_context, ConfigGroup, ConfigList,
                                 Dict, Single)
from slave.recipe_config_types import Path
from slave.recipe_util import Placeholder


def BaseConfig(**_kwargs):
  def render_cmd(lst):
    return [(x if isinstance(x, Placeholder) else str(x)) for x in lst]

  return ConfigGroup(
    # For compatibility with buildbot, the step name must be ascii, which is why
    # this is a 'str' and not a 'basestring'.
    name = Single(str),
    cmd = List(inner_type=(int,basestring,Path,Placeholder),
               jsonish_fn=render_cmd),

    # optional
    env = Dict(item_fn=lambda (k, v): (k, str(v)),
               value_type=(basestring,int,Path,type(None))),
    cwd = Single(Path, jsonish_fn=str, required=False),

    stdout = Single(Placeholder, required=False),
    stderr = Single(Placeholder, required=False),
    stdin = Single(Placeholder, required=False),

    abort_on_failure = Single(bool, required=False),
    allow_subannotations = Single(bool, required=False),
    always_run = Single(bool, required=False),
    can_fail_build = Single(bool, required=False),
    skip = Single(bool, required=False),

    seed_steps = List(basestring),
    followup_fn = Single(collections.Callable, required=False),
    trigger_specs = ConfigList(
        lambda: ConfigGroup(
            properties=Dict(value_type=object),
        ),
    ),

    step_test_data = Single(collections.Callable, required=False),
  )


config_ctx = config_item_context(BaseConfig, {'_DUMMY': ['val']}, 'example')

@config_ctx()
def test(c):
  c.name = 'test'
  c.cmd = [Path('[CHECKOUT]', 'build', 'tools', 'cool_script.py')]
