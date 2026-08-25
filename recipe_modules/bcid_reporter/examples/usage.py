# Copyright 2022 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    bcid_reporter,
    cipd,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  bcid_reporter: bcid_reporter.API
  cipd: cipd.API
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  bcid_reporter: bcid_reporter.TEST_API


def RunSteps(api: DEPS):
  # Report task stage.
  api.bcid_reporter.report_stage("start")
  # Report another stage; the module shouldn't install broker again.
  api.bcid_reporter.report_stage("fetch", server_url="http://test.local")

  # Report cipd digest.
  api.bcid_reporter.report_cipd(
      "deadbeef",
      "example/cipd/package",
      "fakeiid",
      api.path.start_dir / 'attestation.jsonl',
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


def GenTests(api: TEST_DEPS):
  yield api.test('simple') + api.bcid_reporter(54321)
