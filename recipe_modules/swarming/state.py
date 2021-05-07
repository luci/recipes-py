# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from enum import Enum

class TaskState(Enum):
  r"""Enum representing Swarming task states.
  States must be kept in sync with
  https://cs.chromium.org/chromium/infra/luci/appengine/swarming/swarming_rpcs.py?q=TaskState\(
  See the above link for documentation.
  """
  INVALID = 0x00
  RUNNING = 0x10
  PENDING = 0x20
  EXPIRED = 0x30
  TIMED_OUT = 0x40
  BOT_DIED = 0x50
  CANCELED = 0x60
  COMPLETED = 0x70
  KILLED = 0x80
  NO_RESOURCE = 0x100
