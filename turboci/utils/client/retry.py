# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A tuned retry module for TurboCI clients."""

from __future__ import annotations

import dataclasses
import random
import typing

__all__ = [
    'Retry',
]


@dataclasses.dataclass(kw_only=True)
class Retry:
  """Simple retry iterator which calculates delay as:

  d = min(max_delay_sec, base_delay_sec * (backoff_factor ** (attempt-1)))
  delay = random.uniform(d * (1-random_factor), d)
  """

  # The maximum number of retries.
  max_retries: int = 7

  # The base delay for retries in seconds.
  base_delay_sec: float = 0.2

  # The exponential base for retries (e.g. `backoff_factor ** (retry #)`)
  backoff_factor: float = 2.0

  # A cap on the calculated amount of delay.
  max_delay_sec: float = 10.0

  # The actual sleep duration will be less than the strictly calculated delay
  # by this proportion. A value of 0 means no randomness, a value of 1 means
  # anything from 0 to the strictly calculated delay.
  random_factor: float = 0.5

  def attempts(self) -> typing.Generator[float | None, None, None]:
    """Yields the sleep duration to use if the corresponding attempt fails.

    On the final allowed attempt, yields None to indicate that no further
    retries should be made.
    """
    for retry in range(0, max(0, self.max_retries)):
      delay = min(
          self.base_delay_sec * (self.backoff_factor**retry),
          self.max_delay_sec,
      )
      yield random.uniform(delay * (1 - self.random_factor), delay)

    yield None
