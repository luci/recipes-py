# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
from __future__ import annotations

from recipe_engine import post_process

from PB.recipe_modules.recipe_engine.time.examples import jitter as jitter_pb2

DEPS = [
  'assertions',
  'properties',
  'step',
  'time',
]

INLINE_PROPERTIES_PROTO = """
message JitterProps {
  float random_output = 1;
  int32 expected_outcome = 2;
}
"""

PROPERTIES = jitter_pb2.JitterProps


def RunSteps(api, properties):
  random_func = lambda: properties.random_output
  jittered_time = api.time._jitter(100, .10, random_func)
  api.assertions.assertEqual(
    properties.expected_outcome,
    # Rounded because integer math is hard (it was returning 99.999999).
    round(jittered_time)
  )

def GenTests(api):
  yield api.test(
      'low-end',
      api.properties(
          jitter_pb2.JitterProps(random_output=0, expected_outcome=90)),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'middle',
      api.properties(
          jitter_pb2.JitterProps(random_output=.5, expected_outcome=100)),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'high-end',
      api.properties(
          jitter_pb2.JitterProps(random_output=1, expected_outcome=110)),
      api.post_process(post_process.DropExpectation),
  )
