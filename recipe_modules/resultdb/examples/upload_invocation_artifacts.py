# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.resultdb.proto.v1 import artifact
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder

DEPS = [
    'resultdb',
]


def RunSteps(api):
  api.resultdb.upload_invocation_artifacts({
      'a': {
        'content_type': 'text/plain',
        'contents': b'foobar'
      }
  })


def GenTests(api):
  yield api.test(
      'basic',
      api.resultdb.upload_invocation_artifacts(
          recorder.BatchCreateArtifactsResponse(artifacts=[
              artifact.Artifact(
                  artifact_id='a',
                  content_type='text/plain',
                  contents=b'foobar')])),
      api.post_process(DropExpectation),
  )
