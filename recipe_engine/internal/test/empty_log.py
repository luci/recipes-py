# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


class _EmptyLog(str):
  """A special string object equal to the empty string that can be used to
  distinguish logs with no lines and logs containing a single empty line.
  """
  def __new__(cls):
    return super(_EmptyLog, cls).__new__(cls, '')

  def __copy__(self):
    return self

  def __deepcopy__(self, memo):
    return self

EMPTY_LOG = _EmptyLog()
