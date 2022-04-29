# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
  'bcid_reporter',
  'recipe_engine/path',
]

def RunSteps(api):
  # Report task stage.
  api.bcid_reporter.report_stage("start")
  # Report another stage; the module shouldn't install broker again.
  api.bcid_reporter.report_stage("fetch", server_url="http://test.local")

  # Report cipd digest.
  api.bcid_reporter.report_cipd("deadbeef", "example/cipd/package", "fakeiid",
                                  server_url="http://test.local")

  # Report gcs artifact digest.
  api.bcid_reporter.report_gcs("deadbeef", "gs://bucket/path/to/binary",
                                 server_url="http://test.local")


def GenTests(api):
  yield api.test('simple') + api.bcid_reporter(54321)
