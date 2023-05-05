# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.utils import iteritems

import datetime
import json

from google.protobuf import text_format
from google.protobuf import timestamp_pb2

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
  'assertions',
  'buildbucket',
  'properties',
  'step',
]


def RunSteps(api):
  text = text_format.MessageToString(api.buildbucket.build)
  api.step('build', ['echo'] + text.splitlines())
  api.step('hostname', ['echo', api.buildbucket.host])
  api.step('is_critical', ['echo', api.buildbucket.is_critical()])

  api.assertions.assertEqual(
      api.buildbucket.bucket_v1,
      api.properties.get('expected_bucket_v1'))
  api.assertions.assertEqual(
      api.buildbucket.builder_name,
      api.buildbucket.build.builder.builder)
  api.assertions.assertEqual(
      api.buildbucket.gitiles_commit,
      api.buildbucket.build.input.gitiles_commit)

  expected_realm = api.properties.get('expected_realm')
  if expected_realm:
    api.assertions.assertEqual(api.buildbucket.builder_realm, expected_realm)
  else:
    with api.assertions.assertRaises(api.step.InfraFailure):
      api.buildbucket.builder_realm

  expected_full_name = api.properties.get('expected_full_name')
  if expected_full_name:
    api.assertions.assertEqual(api.buildbucket.builder_full_name,
                               expected_full_name)
  else:
    with api.assertions.assertRaises(api.step.InfraFailure):
      api.buildbucket.builder_full_name


def GenTests(api):

  def case(name, **properties):
    return api.test(name) + api.properties(**properties)

  yield case('empty')

  yield case('hostname', **{
      '$recipe_engine/buildbucket': {
          'hostname': 'buildbucket.example.com',
      },
  })

  yield case('legacy-master', **{
      'mastername': 'chromium.fyi',
      'branch': 'beta',
      'revision': 'a' * 40,
  })

  yield case('legacy-patch-props', **{
      'patch_storage': 'gerrit',
      'patch_gerrit_url': 'https://example.googlesource.com/',
      'patch_project': 'a/b',
      'patch_issue': 1,
      'patch_set': 2,
  })

  yield (
      case('ci',
           expected_bucket_v1='luci.test.ci',
           expected_realm='test:ci',
           expected_full_name='test/ci/builder')
      + api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
      )
      + api.post_process(post_process.DropExpectation)
  )

  yield (
      case('ci with experiment',
           expected_bucket_v1='luci.test.ci',
           expected_realm='test:ci',
           expected_full_name='test/ci/builder')
      + api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          experiments=['fake.experiment'],
          execution_timeout=12345,
          start_time=datetime.datetime(2020, 1, 1),
      )
      + api.post_process(post_process.DropExpectation)
  )

  yield (
      case('try',
           expected_bucket_v1='luci.test.try',
           expected_realm='test:try',
           expected_full_name='test/try/builder')
      + api.buildbucket.try_build(
      project='test',
      git_repo='git.example.com/test/repo',
  )
      + api.post_process(post_process.DropExpectation)
  )

  yield (
      case(
          'try with experiment',
          expected_bucket_v1='luci.test.try',
          expected_realm='test:try',
          expected_full_name='test/try/builder')
      + api.buildbucket.try_build(
          project='test',
          git_repo='git.example.com/test/repo',
          experiments=['fake.experiment'],
          execution_timeout=12345,
          start_time=datetime.datetime(2020, 1, 1),
      )
      + api.post_process(post_process.DropExpectation)
  )

  yield(
      case(
          'cron',
          expected_bucket_v1='luci.test.cron',
          expected_realm='test:cron',
          expected_full_name='test/cron/scanner'
      )
      + api.buildbucket.build(build_pb2.Build(
          id=12484724,
          tags=[],
          builder=builder_common_pb2.BuilderID(
              project='test',
              bucket='cron',
              builder='scanner',
          ),
          created_by='user:luci-scheduler@appspot.gserviceaccount.com',
          create_time=timestamp_pb2.Timestamp(seconds=1527292217),
      ))
  )

  try:
    api.buildbucket.ci_build(git_repo='https://just.hostname/')
    assert 0  # pragma: no cover
  except ValueError:
    pass

  try:
    api.buildbucket.ci_build(git_repo='bad.git.repo.example.com')
    assert 0  # pragma: no cover
  except ValueError:
    pass

  try:
    api.buildbucket.ci_build(git_repo='blah://not.supported')
    assert 0  # pragma: no cover
  except ValueError:
    pass
