# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
  'bcid_reporter',
  'recipe_engine/path',
  'recipe_engine/raw_io',
]

def RunSteps(api):
  api.bcid_reporter.report_stage("start")
  api.bcid_reporter.report_cipd("deadbeef", "example/cipd/package", "fakeiid")
  api.bcid_reporter.report_gcs("deadbeef", "gs://bucket/path/to/binary")
  api.bcid_reporter.report_sbom("deadbeef", "gs://bucket/path/to/binary.spdx.jsonl")

def GenTests(api):
    yield api.test(
      'report_step_failure',
            api.override_step_data('snoop: report_stage', retcode=1),
            api.post_process(post_process.MustRun, 'snoop: report_stage (2)'),
            api.post_process(post_process.DoesNotRun, 'snoop: report_stage (3)'),
            api.override_step_data('snoop: report_cipd', retcode=1),
            api.post_process(post_process.MustRun, 'snoop: report_cipd (2)'),
            api.post_process(post_process.DoesNotRun, 'snoop: report_cipd (3)'),
            api.override_step_data('snoop: report_gcs', retcode=1),
            api.post_process(post_process.MustRun, 'snoop: report_gcs (2)'),
            api.post_process(post_process.DoesNotRun, 'snoop: report_gcs (3)'),
            api.override_step_data('snoop: report_sbom', retcode=1),
            api.post_process(post_process.MustRun, 'snoop: report_sbom (2)'),
            api.post_process(post_process.DoesNotRun, 'snoop: report_sbom (3)'),
            api.post_process(post_process.DropExpectation)
    )