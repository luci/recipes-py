# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from .type_definitions import Handler


class ListHandler(Handler):
  """List all of the tests instead of running them."""
  SKIP_RUNLOOP = True

  class ResultStageHandler(Handler.ResultStageHandler):
    @staticmethod
    def handle_Test(test):
      print test.name

    # TODO(iannucci): group tests by dir?
    # TODO(iannucci): print more data about the test in verbose mode?
