# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows randomness in recipes.

This module sets up an internal instance of 'random.Random'. In tests, this is
seeded with `1234`, or a seed of your choosing (using the test_api's `seed()`
method)

All members of `random.Random` are exposed via this API with getattr.

NOTE: This is based on the python `random` module, and so all caveats which
apply there also apply to this (i.e. don't use it for anything resembling
crypto).

Example:

    def RunSteps(api):
      my_list = range(100)
      api.random.shuffle(my_list)
      # my_list is now random!
"""


import random

from recipe_engine import recipe_api

class RandomApi(recipe_api.RecipeApi):
  def __init__(self, module_properties, **kwargs):
    super(RandomApi, self).__init__(**kwargs)
    self._random = random.Random(
        module_properties.get('seed',
                              1234 if self._test_data.enabled else None))

  def __getattr__(self, name):
    """Access a member of `random.Random`."""
    return getattr(self._random, name)
