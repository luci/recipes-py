# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'assertions',
    'properties',
    'step',
    'bcid_verifier',
]


def RunSteps(api):
  api.bcid_verifier.verify_provenance(
      'bcid_policy://default',
      '/archive_dir/artifact',
      '/archive_dir/attestation.intoto.jsonl',
      log_only_mode=api.properties.get('log_only', False))


def GenTests(api):
  yield api.test(
      'enforce-verify',
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'logging-verify',
      api.properties(log_only=True),
      api.post_process(post_process.DropExpectation),
  )
