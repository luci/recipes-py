# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_test_api


class PlatformTestApi(recipe_test_api.RecipeTestApi):
  @staticmethod
  def name(name):
    """Set the platform 'name' for the current test.

    The only three values currently allowed are 'win', 'linux', and 'mac'.
    """
    assert name in ('win', 'linux', 'mac'), 'unknown platform %r' % (name,)
    ret = recipe_test_api.TestData(None)

    # BUG(crbug.com/1508497): TestData is still using short module names!!
    ret.mod_data['platform']['name'] = name
    # HACK: We add an additional bit of test data here for the `path` module so
    # that it can directly know the simulated platform during tests without
    # needing to take a dependency on the platform module.
    #
    # This saves a lot of complexity re: interdependency.
    ret.mod_data['path']['platform.name'] = name
    return ret

  @recipe_test_api.mod_test_data
  @staticmethod
  def bits(bits):
    """Set the bitness for the current test.

    The only two values currently allowed are 32 and 64.
    """
    assert bits in (32, 64), 'unknown bitness %r' % (bits,)
    return bits

  @recipe_test_api.mod_test_data
  @staticmethod
  def arch(arch):
    """Set the architecture for the current test.

    The only two values currently allowed are 'linux' and 'arm'.
    """
    assert arch in ('intel', 'arm'), 'unknown arch %r' % (arch,)
    return arch

  def __call__(self, name, bits, arch='intel'):
    return self.name(name) + self.bits(bits) + self.arch(arch)
