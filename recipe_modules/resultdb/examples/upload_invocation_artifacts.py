# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.resultdb.proto.v1 import artifact
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import resultdb


@dataclass
class DEPS(RecipeScriptApi):
  resultdb: resultdb.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  resultdb: resultdb.TEST_API


def RunSteps(api: DEPS):
  api.resultdb.upload_invocation_artifacts({
      'a': {
          'content_type': 'text/plain',
          'contents': b'foobar'
      },
      'b': {
          'content_type': 'text/plain',
          'gcs_uri': 'gs://test-bucket/artifact/b.txt'
      },
      'c': {
          'content_type': 'text/plain',
          'contents': 'string_foobar'
      },
  })


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.resultdb.upload_invocation_artifacts(
          recorder.BatchCreateArtifactsResponse(artifacts=[
              artifact.Artifact(
                  artifact_id='a',
                  content_type='text/plain',
                  contents=b'foobar'),
              artifact.Artifact(
                  artifact_id='b',
                  content_type='text/plain',
                  gcs_uri='gs://test-bucket/artifact/b.txt'),
              artifact.Artifact(
                  artifact_id='c',
                  content_type='text/plain',
                  contents=b'string_foobar')
          ])),
      api.post_process(DropExpectation),
  )
