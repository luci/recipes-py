# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from past.builtins import basestring

from recipe_engine import recipe_test_api


class PlatformTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def name(name):
    """Set the platform 'name' for the current test.

    The only three values currently allowed are 'win', 'linux', and 'mac'.
    """
    assert name in ('win', 'linux', 'mac'), 'unknown platform %r' % (name,)
    return name

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

  @recipe_test_api.mod_test_data
  @staticmethod
  def mac_release(version):
    """Set the version number for the `mac_release()` method for the current
    test.

    This should be a string like '10.14.0'.
    """
    assert isinstance(version, basestring), ('bad version (not string): %r'
                                             % (version,))
    assert version, 'bad version (empty): %r' % (version,)
    return version

  def __call__(self, name, bits, arch='intel', mac_release='10.13.5'):
    return (
      self.name(name) + self.bits(bits) + self.arch(arch)
      + self.mac_release(mac_release))
