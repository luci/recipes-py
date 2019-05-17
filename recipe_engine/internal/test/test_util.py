# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This module contians miscellaneous test-related internal functions."""


def filesystem_safe(name):
  """Returns a filesystem safe version of a test name.

  Args:

    * name (str) - The name of a test case, as provided to `api.test` inside
      a GenTests generator.

  Returns a str which is nominally safe for use as a file name.
  """
  return ''.join('_' if c in '<>:"\\/|?*\0' else c for c in name)
