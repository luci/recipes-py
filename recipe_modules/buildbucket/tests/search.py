# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import (
    build as build_pb2,
    builder_common as builder_common_pb2,
    builds_service as builds_service_pb2,
    common as common_pb2,
)
from PB.recipe_modules.recipe_engine.buildbucket.tests import (properties as
                                                               properties_pb2)

DEPS = [
  'buildbucket',
  'properties',
  'raw_io',
  'runtime',
  'step'
]

PROPERTIES = properties_pb2.SearchInputProps


def RunSteps(api, props):
  limit = api.properties.get('limit')

  test_data = None
  if props.builds:
    test_data = props.builds

  if props.dup_predicate:
    predicate = [
        builds_service_pb2.BuildPredicate(
            gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),),
        builds_service_pb2.BuildPredicate(
            gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),)
    ]
    builds = api.buildbucket.search_with_multiple_predicates(
        predicate,
        limit=limit,
        fields=['builder', 'id', 'status', 'create_time'],
        test_data=test_data,
    )
  else:
    predicate = builds_service_pb2.BuildPredicate(
        gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),)
    builds = api.buildbucket.search(
        predicate,
        limit=limit,
        fields=['builder', 'id', 'status', 'create_time'],
        test_data=test_data,
    )
  assert limit is None or len(builds) <= limit
  pres = api.step.active_result.presentation
  for b in builds:
    pres.logs['build %s' % b.id] = [
      l.rstrip() for l in
      json_format.MessageToJson(b, sort_keys=True).splitlines()
    ]


def GenTests(api):

  def build():
    return api.buildbucket.try_build(
        project='chromium',
        builder='Builder',
        git_repo='https://chromium.googlesource.com/chromium/src',
    )

  yield api.test(
      'basic',
      build(),
  )

  def build_status(id, status=common_pb2.SUCCESS, builder='chromium/try/test'):
    project, bucket, builder = builder.split('/')
    return build_pb2.Build(
        id=id,
        status=status,
        builder=builder_common_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
    )

  yield api.test(
      'props',
      build(),
      api.properties(
          properties_pb2.SearchInputProps(
              builds=[
                  build_status(id=3, builder='chromium/try/foo'),
                  build_status(id=4, builder='chromium/try/bar'),
              ],),),
  )

  yield api.test(
      'two builds',
      build(),
      api.buildbucket.simulated_search_results([
          build_status(id=1),
          build_status(id=2, status=common_pb2.FAILURE),
      ]),
  )

  yield api.test(
      'search failed',
      build(),
      api.step_data(
          'buildbucket.search',
          api.raw_io.stream_output_text('there was a problem'),
          retcode=1),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'two builds two predicates, simulated',
      build(),
      api.properties(dup_predicate=True),
      api.properties(properties_pb2.SearchInputProps(dup_predicate=True,),),
      api.buildbucket.simulated_multi_predicates_search_results([
          build_status(id=1),
          build_status(id=2, status=common_pb2.FAILURE),
      ],),
  )

  yield api.test(
      'two builds two predicates with test data prop',
      build(),
      api.properties(
          properties_pb2.SearchInputProps(
              builds=[
                  build_status(id=3, builder='chromium/try/foo'),
                  build_status(id=4, builder='chromium/try/bar'),
              ],
              dup_predicate=True),),
      api.buildbucket.simulated_multi_predicates_search_results([
          build_status(id=1),
          build_status(id=2, status=common_pb2.FAILURE),
      ],),
  )

  yield api.test(
      'error', build(),
      api.buildbucket.simulated_batch_search_output(
          builds_service_pb2.BatchResponse(
              responses=[
                  dict(error=dict(
                      code=1,
                      message='bad',
                  ),),
              ],)) + api.expect_status('INFRA_FAILURE'))
