# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import text_format

DEPS = [
  'buildbucket',
  'properties',
  'step',
]


def RunSteps(api):
  text = text_format.MessageToString(api.buildbucket.build)
  api.step('build', ['echo'] + text.splitlines())


  child_build_tags = [
      '%s:%s' % t
      for t in api.buildbucket.tags_for_child_build.iteritems()
  ]
  api.step('tags_for_child_build', ['echo'] + child_build_tags)

  assert api.buildbucket.bucket_v1 == api.properties.get('expected_bucket_v1')
  assert api.buildbucket.builder_name == api.buildbucket.build.builder.builder
  assert api.buildbucket.gitiles_commit == (
      api.buildbucket.build.input.gitiles_commit)


def GenTests(api):

  def case(name, **properties):
    return api.test(name) + api.properties(**properties)

  def legacy_build(name, **buildbucket_build):
    return case(name, buildbucket={'build': buildbucket_build})

  yield case('empty')

  yield case('serialized buildbucket property', buildbucket=json.dumps({
    'build': {'id': '123456789'}
  }))

  yield legacy_build('v1 build with id', id='123456789')

  yield legacy_build('v1 empty buildset', tags=['buildset:'])
  yield legacy_build('v1 unknown buildset format', tags=['buildset:x'])

  yield legacy_build('v1 gerrit change', tags=[
      'buildset:patch/gerrit/chromium-review.googlesource.com/1/2',
  ])

  yield legacy_build('v1 gitiles commit', tags=[
      ('buildset:commit/gitiles/chromium.googlesource.com/chromium/src/+/'
       'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
  ])
  yield legacy_build('v1 gitiles commit, invalid', tags=[
      'buildset:commit/gitiles/a/b/c/d'
  ])
  yield legacy_build(
      'v1 created_by',
      created_by='user:jane@example.com')
  yield legacy_build(
      'v1 created_ts',
      created_ts=1546473600000000)

  yield case(
      'buildbot gitiles commit',
      revision='a' * 40,
  )
  yield case(
      'buildbot gitiles commit, parent_got_revision',
      parent_got_revision='a' * 40,
  )
  yield case(
      'buildbot gitiles commit, both revision and parent_got_revision',
      revision='a' * 40,
      parent_got_revision='b' * 40,
  )
  yield case(
      'buildbot gitiles commit, invalid revision',
      revision='deafbeef',  # too short
  )
  yield case(
      'buildbot gitiles commit, HEAD revision',
      revision='HEAD',
  )

  yield case(
      'buildbot gerrit change',
      patch_storage='gerrit',
      patch_gerrit_url='https://example.googlesource.com/',
      patch_project='a/b',
      patch_issue=1,
      patch_set=2,
      buildbucket={
        'build': {
          'tags': [
             'buildset:patch/gerrit/chromium-review.googlesource.com/1/2',
          ],
        },
      },
  )
  yield case(
      'buildbot gerrit change, patch_gerrit_url without scheme',
      patch_storage='gerrit',
      patch_gerrit_url='example.googlesource.com',
      patch_project='a/b',
      patch_issue=1,
      patch_set=2,
  )
  yield case(
      'buildbot gerrit change, patch_gerrit_url with unexpected scheme',
      patch_storage='gerrit',
      patch_gerrit_url='ftp://example.googlesource.com',
      patch_project='a/b',
      patch_issue=1,
      patch_set=2,
  )
  yield case(
      'buildbot gerrit change with revision',
      revision='a' * 40,
      patch_storage='gerrit',
      patch_gerrit_url='https://example.googlesource.com/',
      patch_project='a/b',
      patch_issue=1,
      patch_set=2,
  )
  yield case(
      'buildbot gerrit change, issue and patchset properties',
      patch_storage='gerrit',
      patch_gerrit_url='https://example.googlesource.com/',
      patch_project='a/b',
      issue=1,
      patchset=2,
  )
  yield case(
      'buildbot gerrit change, no project',
      patch_storage='gerrit',
      patch_gerrit_url='https://example.googlesource.com/',
      patch_issue=1,
      patch_set=2,
  )
  yield case(
      'buildbot gerrit change, string issue',
      patch_storage='gerrit',
      patch_gerrit_url='https://example.googlesource.com/',
      patch_project='a/b',
      patch_issue='1',
      patch_set=2,
  )
  yield case(
      'buildbot gerrit change, string issue, not a number',
      patch_storage='gerrit',
      patch_gerrit_url='https://example.googlesource.com/',
      patch_project='a/b',
      patch_issue='x',
      patch_set=2,
  )

  yield (
      legacy_build(
          'v1 luci builder id',
          project='chromium',
          bucket='luci.chromium.try',
          tags=['builder:linux']) +
      api.properties(expected_bucket_v1='luci.chromium.try'))

  yield case(
      'v1 buildbot builder id', mastername='chromium', buildername='linux')

  yield legacy_build('v1 tags', tags=['a:b', 'c:d'])
  yield legacy_build('v1 hidden tags', tags=[
      'buildset:patch/gerrit/chromium-review.googlesource.com/1/2',
      ('buildset:commit/gitiles/chromium.googlesource.com/chromium/src/+/'
       'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
      'build_address:bucket/builder/123',
      'builder:linux',
  ])
