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
import sys
from builtins import range

from recipe_engine import recipe_api


# TODO(crbug/1147793) When python2 support is removed this class can be removed
# and RandomApi can just use random.Random, this class is only needed during the
# migration to resolve implementation differences that result in different
# random results that impact expectation files
if sys.version_info.major >= 3:

  class _Random(random.Random):

    def randrange(self, start, stop=None, step=1):
      return self.choice(range(start, stop, step))

    def choice(self, seq):
      return seq[int(self.random() * len(seq))]

    def shuffle(self, x, random=None):
      if random is None:
        random = self.random
      return super(_Random, self).shuffle(x, random=random)

else:  # pragma: no cover
  # TODO: Remove when ripping out py2.
  _Random = random.Random


class RandomApi(recipe_api.RecipeApi):
  def __init__(self, module_properties, **kwargs):
    super(RandomApi, self).__init__(**kwargs)
    self._random = _Random(
        module_properties.get('seed',
                              1234 if self._test_data.enabled else None))

  def __getattr__(self, name):
    """Access a member of `random.Random`."""
    return getattr(self._random, name)
