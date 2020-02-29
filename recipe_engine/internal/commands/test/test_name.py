# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

# TODO(crbug.com/1057298) Recipes can actually have '.' characters in their name
# and this will fail to get the recipe name. Recipes should be restricted from
# having '.' characters in their name.
def split(test_name):
  """Split a fully-qualified test name.

  Returns:
    A tuple: (recipe name, simple test name)
  """
  recipe, simple_test_name = test_name.split('.', 1)
  return recipe, simple_test_name
