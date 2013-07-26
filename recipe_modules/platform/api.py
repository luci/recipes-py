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

    # Sometimes machine() lies, sometimes process() lies, so take their max.
    machine_bits = norm_bits(platform.machine())
    processor_bits = norm_bits(platform.processor())
    self._bits = max(machine_bits, processor_bits)
    self._arch = 'intel'

    if self._mock is not None:
      # Default to linux/64, unless test case says otherwise.
      self._name = norm_plat(self._mock.get('name', 'linux'))
      self._bits = norm_bits(self._mock.get('bits', 64))

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
    return self._bits

  @property
  def arch(self):
    return self._arch
