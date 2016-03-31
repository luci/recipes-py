#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import subprocess
import sys


def CommonChecks(input_api, output_api):
  def tests(*path):
    return input_api.canned_checks.GetUnitTestsInDirectory(
        input_api,
        output_api,
        input_api.os_path.join(*path),
        whitelist=[r'.+_test\.py'])

  results = []

  results.extend(input_api.canned_checks.PanProjectChecks(
      input_api, output_api))

  results.extend(input_api.RunTests(
      tests('recipe_engine', 'unittests') +
      tests('unittests')))

  return results


CheckChangeOnUpload = CommonChecks
CheckChangeOnCommit = CommonChecks
