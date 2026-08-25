# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    bcid_verifier,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  bcid_verifier: bcid_verifier.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


def RunSteps(api: DEPS):
  api.bcid_verifier.verify_provenance(
      'bcid_policy://default',
      '/archive_dir/artifact',
      '/archive_dir/attestation.intoto.jsonl',
      log_only_mode=api.properties.get('log_only', False))


def GenTests(api: TEST_DEPS):
  yield api.test(
      'enforce-verify',
      api.post_check(
          post_process.MustRun,
          'install infra/tools/security/bcid_verifier.ensure_installed'),
      api.post_check(
          post_process.StepCommandContains,
          'bcid_verifier: verify provenance',
          [
              "-bcid-policy",
              "bcid_policy://default",
              "-artifact-path",
              "/archive_dir/artifact",
              "-attestation-path",
              "/archive_dir/attestation.intoto.jsonl",
              "verification-mode",
              "VERIFY_FOR_ENFORCEMENT",
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'logging-verify',
      api.properties(log_only=True),
      api.post_check(
          post_process.MustRun,
          'install infra/tools/security/bcid_verifier.ensure_installed'),
      api.post_check(
          post_process.StepCommandContains,
          'bcid_verifier: verify provenance',
          [
              "-bcid-policy",
              "bcid_policy://default",
              "-artifact-path",
              "/archive_dir/artifact",
              "-attestation-path",
              "/archive_dir/attestation.intoto.jsonl",
              "verification-mode",
              "VERIFY_FOR_LOGGING",
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
