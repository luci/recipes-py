# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import signal

pid = int(sys.argv[1])
if sys.platform.startswith('win'):
  os.kill(pid, signal.CTRL_BREAK_EVENT)  # pylint: disable=no-member
else:
  os.kill(pid, signal.SIGTERM)
