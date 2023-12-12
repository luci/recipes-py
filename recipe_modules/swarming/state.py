# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from enum import Enum

class TaskState(Enum):
  r"""Enum representing Swarming task states.
  States must be kept in sync with
  https://crsrc.org/i/luci/appengine/swarming/server/task_result.py;drc=733d5d3b5299408cbc6a5e5b33b1a461ea9e0acd
  See the above link for documentation.
  """
  # TODO(INVALID) state is actually not used anywhere. We should delete it from
  # protos.
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
  CLIENT_ERROR = 0x200
