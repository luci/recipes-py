#!/usr/bin/env python

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
  return input_api.RunTests(
      tests('recipe_engine', 'unittests') +
      tests('unittests'))

CheckChangeOnUpload = CommonChecks
CheckChangeOnCommit = CommonChecks
