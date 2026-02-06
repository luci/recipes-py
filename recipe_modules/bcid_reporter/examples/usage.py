# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'bcid_reporter',
    'recipe_engine/cipd',
    'recipe_engine/path',
]

def RunSteps(api):
  # Report task stage.
  api.bcid_reporter.report_stage("start")
  # Report another stage; the module shouldn't install broker again.
  api.bcid_reporter.report_stage("fetch", server_url="http://test.local")

  # Report cipd digest.
  api.bcid_reporter.report_cipd(
      "deadbeef",
      "example/cipd/package",
      "fakeiid",
      server_url="http://test.local")

  # Report gcs artifact digest.
  api.bcid_reporter.report_gcs(
      "deadbeef", "gs://bucket/path/to/binary", server_url="http://test.local")

  # Report sbom artifact digest.
  api.bcid_reporter.report_sbom(
      "deadbeef",
      "gs://bucket/path/to/binary.spdx.jsonl", ["beefdead", "3735928559"],
      server_url="http://test.local")

  api.bcid_reporter.report_sbom(
      "deadbeef",
      "gs://bucket/path/to/binary.spdx.jsonl",
      "beefdead",
      server_url="http://test.local")

  api.bcid_reporter.create_from_yaml(
      api.path.start_dir / 'fake-package.yaml',
      refs=['latest'],
      tags={'key': 'value'},
      metadata=[api.cipd.Metadata(key='k', value='v')],
      pkg_vars={'pkg_var_1': 'pkg_val_1'},
      compression_level=9,
      verification_timeout='20m')

  api.bcid_reporter.create_from_pkg(
      pkg_def=api.cipd.PackageDefinition(
          'infra/fake-package',
          api.path.start_dir / 'some_subdir',
          'copy',
          preserve_mtime=True,
          preserve_writable=True),
      refs=['latest'],
      tags={'key': 'value'},
      metadata=[api.cipd.Metadata(key='k', value='v')])

def GenTests(api):
  yield api.test('simple') + api.bcid_reporter(54321)
