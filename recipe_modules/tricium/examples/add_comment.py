# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from PB.tricium.data import Data
from PB.go.chromium.org.luci.common.proto.findings import findings as findings_pb

DEPS = ['buildbucket', 'proto', 'properties', 'tricium']

PROPERTIES = {
    'trigger_type_error': Property(kind=bool, default=False),
}

COMMENT_1 = {
    'category': 'test category',
    'message': 'test message',
    'path': 'path/to/file',
}

COMMENT_2 = {
    'category':
        'another category',
    'message':
        'another test message',
    'path':
        'path/to/file/2',
    'start_line':
        1,
    'start_char':
        10,
    'end_line':
        1,
    'end_char':
        20,
    'suggestions': [
        {
            'replacements': [{
                'path': 'hello.cc',
                'replacement': 'hello()',
                'start_line': 123,
                'start_char': 10,
                'end_line': 441,
                'end_char': 20,
            }],
        },
        {
            'description':
                'commit message typo',
            'replacements': [{
                'path': '',
                'replacement': 's/tyop/typo',
                'start_line': 1,
                'start_char': 1,
                'end_line': 1,
                'end_char': 20,
            }],
        },
    ],
}


def CreateExpectedFinding(api, input_comment):
  cl = api.buildbucket.build.input.gerrit_changes[0]
  gerrit_ref = {
      'host': cl.host,
      'project': cl.project,
      'change': cl.change,
      'patchset': cl.patchset,
  }
  expected = {
      'category': input_comment['category'],
      'location': {
          'gerrit_change_ref': gerrit_ref,
          'file_path': input_comment['path'],
      },
      'severity_level': 'WARNING',
      'message': input_comment['message'],
  }
  if input_comment.get('start_line', 0) > 0:
    expected['location']['range'] = {
        'start_line': input_comment['start_line'],
        'start_column': input_comment['start_char'] + 1,
        'end_line': input_comment['end_line'],
        'end_column': input_comment['end_char'] + 1,
    }

  for s in input_comment.get('suggestions', []):
    fix = {'description': s.get('description', ''), 'replacements': []}
    for r in s['replacements']:
      fix['replacements'].append({
          'location': {
              'gerrit_change_ref': gerrit_ref,
              'file_path': r['path'] if r['path'] else 'COMMIT_MSG',
          },
          'new_content': r['replacement'],
      })
      if r.get('start_line', 0) > 0:
        fix['replacements'][-1]['location']['range'] = {
            'start_line': r['start_line'],
            'start_column': r['start_char'] + 1,
            'end_line': r['end_line'],
            'end_column': r['end_char'] + 1,
        }

    expected.setdefault('fixes', []).append(fix)

  return expected


def RunSteps(api, trigger_type_error):
  filename = 'path/to/file'
  if trigger_type_error:
    COMMENT_2['start_line'] = str(COMMENT_2['start_line'])

  api.tricium.add_comment(**COMMENT_1)
  api.tricium.add_comment(**COMMENT_2)

  # Duplicate comments aren't entered.
  api.tricium.add_comment(**COMMENT_1)

  # verify the produced comments/findings
  expected_comments = [
      Data.Comment(**COMMENT_1),
      Data.Comment(**COMMENT_2),
  ]

  if api.buildbucket.build.input.gerrit_changes:
    expected_finding1 = CreateExpectedFinding(api, COMMENT_1)
    expected_finding2 = CreateExpectedFinding(api, COMMENT_2)
    expected_findings = [
        api.proto.decode(
            json.dumps(expected_finding1), findings_pb.Finding, 'JSONPB'),
        api.proto.decode(
            json.dumps(expected_finding2), findings_pb.Finding, 'JSONPB'),
    ]
    assert api.tricium._findings == expected_findings, (
        'findings: %s\nexpected: %s' %
        (api.tricium._findings, expected_findings))
  else:
    assert not api.tricium._findings

  api.tricium.write_comments()


def GenTests(api):
  yield api.test('basic', api.buildbucket.try_build(project='chrome'))
  yield (api.test('type_error', api.buildbucket.try_build(project='chrome')) +
         api.properties(trigger_type_error=True) +
         api.expect_exception('TypeError') +
         api.post_process(post_process.DropExpectation))
  yield (api.test('no_gerrit_change') +
         api.post_process(post_process.DropExpectation))
