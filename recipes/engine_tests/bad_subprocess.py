# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that daemons that hang on to STDOUT can't cause the engine to hang."""

DEPS = [
  'python',
]

def RunSteps(api):
  api.python.inline("bad deamon", """
  import os
  import time
  import sys

  print "parent"
  pid = os.fork()
  if pid > 0:
    "parent leaves"
    sys.exit(0)

  print "child"
  pid = os.fork()
  if pid > 0:
    "child leaves"
    sys.exit(0)

  print "daemon sleepin'"
  time.sleep(30)

  print "ROAAARRRR!!!"
  """)

def GenTests(api):
  yield api.test('basic')

