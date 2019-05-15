# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import json_format

# pylint: disable=import-error
from PB.recipe_engine.test_result import TestResult


def run_diff(baseline, actual, json_file):
  """Implementation of the 'test diff' command.

  Args:
    * baseline (readable file obj) - The "pre" half of the diff. Must contain
      a TestResult proto message in JSONPB form.
    * actual (readable file obj) - The "post" half of the diff. Must contain
      a TestResult proto message in JSONPB form.
    * json_file (writeable file obj|None) - If not-None, the diff will be
      written as a TestResult message in JSONPB form.

  Returns 0 if no diff between baseline and actual, otherwise 1
  """
  baseline_proto = TestResult()
  json_format.ParseDict(json.load(baseline), baseline_proto)

  actual_proto = TestResult()
  json_format.ParseDict(json.load(actual), actual_proto)

  success, results_proto = _diff_internal(baseline_proto, actual_proto)

  if json_file:
    obj = json_format.MessageToDict(
        results_proto, preserving_proto_field_name=True)
    json.dump(obj, json_file)

  return 0 if success else 1


def _diff_internal(baseline_proto, actual_proto):
  results_proto = TestResult(version=1, valid=True)

  if (not baseline_proto.valid or
      not actual_proto.valid or
      baseline_proto.version != 1 or
      actual_proto.version != 1):
    results_proto.valid = False
    return (False, results_proto)

  success = True

  for filename, details in actual_proto.coverage_failures.iteritems():
    actual_uncovered_lines = set(details.uncovered_lines)
    baseline_uncovered_lines = set(
        baseline_proto.coverage_failures[filename].uncovered_lines)
    cover_diff = actual_uncovered_lines.difference(baseline_uncovered_lines)
    if cover_diff:
      success = False
      results_proto.coverage_failures[
          filename].uncovered_lines.extend(cover_diff)

  for test_name, test_failures in actual_proto.test_failures.iteritems():
    for test_failure in test_failures.failures:
      found = False
      for baseline_test_failure in baseline_proto.test_failures[
          test_name].failures:
        if test_failure == baseline_test_failure:
          found = True
          break
      if not found:
        success = False
        results_proto.test_failures[test_name].failures.extend([test_failure])

  actual_uncovered_modules = set(actual_proto.uncovered_modules)
  baseline_uncovered_modules = set(baseline_proto.uncovered_modules)
  uncovered_modules_diff = actual_uncovered_modules.difference(
      baseline_uncovered_modules)
  if uncovered_modules_diff:
    success = False
    results_proto.uncovered_modules.extend(uncovered_modules_diff)

  actual_unused_expectations = set(actual_proto.unused_expectations)
  baseline_unused_expectations = set(baseline_proto.unused_expectations)
  unused_expectations_diff = actual_unused_expectations.difference(
      baseline_unused_expectations)
  if unused_expectations_diff:
    success = False
    results_proto.unused_expectations.extend(unused_expectations_diff)

  return (success, results_proto)
