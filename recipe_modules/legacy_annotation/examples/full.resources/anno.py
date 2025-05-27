# -*- coding: utf-8 -*-
# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import textwrap

anno = textwrap.dedent('''
  @@@SEED_STEP@Initial Step@@@
  @@@STEP_CURSOR@Initial Step@@@

  @@@STEP_STARTED@@@
  @@@STEP_LOG_LINE@$debug@Aloha@@@
  @@@STEP_LOG_LINE@$debug@This is the very first step!@@@
  @@@STEP_LOG_LINE@foo@This is the log for log name foo!@@@
  @@@STEP_LOG_END@foo@@@
  @@@STEP_LOG_END@$debug@@@
  @@@STEP_TEXT@Hi! This is the first step!@@@
  @@@STEP_CLOSED@@@

  @@@SEED_STEP@Step Nested@@@
  @@@SEED_STEP@Step Nested.Child 1@@@
  @@@STEP_CURSOR@Step Nested.Child 1@@@
  @@@STEP_STARTED@@@
  @@@STEP_NEST_LEVEL@1@@@
  @@@STEP_LOG_LINE@$debug@Hey there!@@@
  @@@STEP_LOG_LINE@$debug@You are in a child step now!@@@
  @@@STEP_LOG_END@$debug@@@
  @@@STEP_CLOSED@@@
  @@@SEED_STEP@Step Nested.Child 💣@@@
  @@@STEP_CURSOR@Step Nested.Child 💣@@@
  @@@STEP_STARTED@@@
  @@@STEP_NEST_LEVEL@1@@@
  @@@STEP_LOG_LINE@$debug@Explosion!!!!@@@
  @@@STEP_LOG_END@$debug@@@
  @@@STEP_CLOSED@@@
  @@@STEP_CURSOR@Step Nested@@@
  @@@STEP_STARTED@@@
  @@@STEP_CLOSED@@@

  @@@SEED_STEP@Set Property@@@
  @@@STEP_CURSOR@Set Property@@@
  @@@STEP_STARTED@@@
  @@@STEP_LOG_LINE@$debug@Try Setting property@@@
  @@@STEP_LOG_END@$debug@@@
  @@@SET_BUILD_PROPERTY@obj_prop@{"hi": "there"}@@@
  @@@SET_BUILD_PROPERTY@str_prop@"hi"@@@
  @@@STEP_CLOSED@@@

  @@@SEED_STEP@Failed Step@@@
  @@@STEP_CURSOR@Failed Step@@@
  @@@STEP_STARTED@@@
  @@@STEP_LOG_LINE@$debug@This step has failed@@@
  @@@STEP_LOG_END@$debug@@@
  @@@STEP_FAILURE@@@
  @@@STEP_CLOSED@@@
''').splitlines()

for line in anno:
  if line:
    print(line)
