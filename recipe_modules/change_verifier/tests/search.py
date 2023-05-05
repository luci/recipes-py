# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.cv.api.v0 import run as run_pb
from PB.go.chromium.org.luci.cv.api.v0 import service_runs as service_runs_pb

DEPS = [
    'change_verifier',
    'proto',
]


def RunSteps(api):
  # Lookup Runs by CL.
  runs = api.change_verifier.search_runs(
      'prj', cls=('x-review.googlesource.com', 123), step_name='search1cl')
  assert len(runs) > 0

  # Search for Runs that contain 2 particular CLs (and may contain others).
  runs = api.change_verifier.search_runs(
      'prj',cls=[
          ('x-review.googlesource.com', 123),
          ('x-review.googlesource.com', 222)],
      step_name='search2cls')
  assert len(runs) > 0

  # We can lookup Runs by project, and specify a limit.
  runs = api.change_verifier.search_runs(
      'prj', limit=50, step_name='search-project')
  assert len(runs) == 50


def make_runs(count=1):
  """Generates response Runs for a test."""
  runs = []
  for i in range(count):
    runs.append(run_pb.Run(id='projects/prj/runs/%d' % i))
  return runs


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('search1cl.request page 1',
                    stdout=api.proto.output(
                        service_runs_pb.SearchRunsResponse(runs=make_runs()))),
      api.step_data('search2cls.request page 1',
                    stdout=api.proto.output(
                        service_runs_pb.SearchRunsResponse(runs=make_runs()))),
      api.step_data('search-project.request page 1',
                    stdout=api.proto.output(
                        service_runs_pb.SearchRunsResponse(
                            runs=make_runs(32),
                            next_page_token='abcd'))),
      api.step_data('search-project.request page 2',
                    stdout=api.proto.output(
                        service_runs_pb.SearchRunsResponse(
                            runs=make_runs(32)))),
  )

  yield api.test(
      'error',
      api.step_data('search1cl.request page 1', retcode=1),
      status='INFRA_FAILURE',
  )
