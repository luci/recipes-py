# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
import platform

from slave import recipe_api


def norm_plat(plat):
  if plat.startswith('linux'):
    return 'linux'
  elif plat.startswith(('win', 'cygwin')):
    return 'win'
  elif plat.startswith(('darwin', 'mac')):
    return 'mac'
  else:  # pragma: no cover
    raise ValueError('Don\'t understand platform "%s"' % plat)


def norm_bits(arch):
  return 64 if '64' in str(arch) else 32


class PlatformApi(recipe_api.RecipeApi):
  """
  Provides host-platform-detection properties.

  Mocks:
    name (str): A value equivalent to something that might be returned by
      sys.platform.
    bits (int): Either 32 or 64.
  """

  def __init__(self, **kwargs):
    super(PlatformApi, self).__init__(**kwargs)
    self._name = norm_plat(sys.platform)

    self._arch = 'intel'
    self._bits = norm_bits(platform.machine())

    if self._test_data.enabled:
      # Default to linux/64, unless test case says otherwise.
      self._name = norm_plat(self._test_data.get('name', 'linux'))
      self._bits = norm_bits(self._test_data.get('bits', 64))
    else:  # pragma: no cover
      # platform.machine is based on running kernel. It's possible to use 64-bit
      # kernel with 32-bit userland, e.g. to give linker slightly more memory.
      # Distinguish between different userland bitness by querying
      # the python binary.
      if (self._name == 'linux' and
          self._bits == 64 and
          platform.architecture()[0] == '32bit'):
        self._bits = 32

  @property
  def is_win(self):
    return self.name == 'win'

  @property
  def is_mac(self):
    return self.name == 'mac'

  @property
  def is_linux(self):
    return self.name == 'linux'

  @property
  def name(self):
    return self._name

  @property
  def bits(self):
    # The returned bitness corresponds to the userland. If anyone ever wants
    # to query for bitness of the kernel, another accessor should be added.
    return self._bits

  @property
  def arch(self):
    return self._arch

  @staticmethod
  def normalize_platform_name(platform):
    """One of python's sys.platform values -> 'win', 'linux' or 'mac'."""
    return norm_plat(platform)  # pragma: no cover
