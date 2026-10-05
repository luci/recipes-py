# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations


from typing import Any, Self


class _EmptyLog(str):
  """A special string object equal to the empty string that can be used to
  distinguish logs with no lines and logs containing a single empty line.
  """
  def __new__(cls) -> Self:
    return super().__new__(cls, '')

  def __copy__(self) -> Self:
    return self

  def __deepcopy__(self, memo: dict[int, Any]) -> Self:
    return self


EMPTY_LOG = _EmptyLog()
