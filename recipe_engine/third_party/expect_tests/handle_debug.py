# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
import pdb

from .type_definitions import Handler


class DebugHandler(Handler):
  """Execute each test under the pdb debugger."""
  SKIP_RUNLOOP = True

  class ResultStageHandler(Handler.ResultStageHandler):
    @staticmethod
    def handle_Test(test):
      dbg = pdb.Pdb()
      for path, line, funcname in test.breakpoints:
        dbg.set_break(path, line, funcname=funcname)

      dbg.reset()

      def dispatch_thunk(*args):
        """Allows us to continue until the actual breakpoint."""
        val = dbg.trace_dispatch(*args)
        dbg.set_continue()
        sys.settrace(dbg.trace_dispatch)
        return val
      sys.settrace(dispatch_thunk)
      try:
        test.run()
      except pdb.bdb.BdbQuit:
        pass
      finally:
        dbg.quitting = 1
        sys.settrace(None)
