# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api

class PlatformTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def name(name):
    assert name in ('win', 'linux', 'mac')
    return name

  @recipe_test_api.mod_test_data
  @staticmethod
  def bits(bits):
    assert bits in (32, 64)
    return bits

  def __call__(self, name, bits):
    return self.name(name) + self.bits(bits)

