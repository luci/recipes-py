# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.common.proto.findings import findings as findings_pb

DEPS = [
    'buildbucket',
    'findings',
    'properties',
]

PROPERTIES = findings_pb.Findings


def RunSteps(api, props):
  api.findings.upload_findings(props.findings)


def GenTests(api):
  gerrit_change_ref = findings_pb.Location.GerritChangeReference(
      host='chromium-review.googlesource.com',
      project='infra',
      change=123456,
      patchset=7,
  )
  yield (api.test('basic') + api.buildbucket.try_build(project='infra') +
         api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(
                             start_line=1,
                             start_column=2,
                             end_line=1,
                             end_column=6,
                         ),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                     fixes=[
                         findings_pb.Fix(
                             description='fix desc',
                             replacements=[
                                 findings_pb.Fix.Replacement(
                                     location=findings_pb.Location(
                                         gerrit_change_ref=gerrit_change_ref,
                                         file_path='test-file-path',
                                         range=findings_pb.Location.Range(
                                             start_line=1,
                                             start_column=2,
                                             end_line=1,
                                             end_column=6,
                                         ),
                                     ),
                                     new_content='typo'),
                             ])
                     ])
             ])))

  yield (api.test('empty findings') +
         api.buildbucket.try_build(project='infra') +
         api.properties(findings_pb.Findings()) +
         api.post_process(post_process.DropExpectation))

  yield (api.test('ResultDB not enabled') + api.properties(
      findings_pb.Findings(findings=[
          findings_pb.Finding(
              category='SpellChecker',
              location=findings_pb.Location(
                  gerrit_change_ref=gerrit_change_ref,
                  file_path='test-file-path',
              ),
              message='This is a typo',
              severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
          )
      ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'ResultDB MUST be enabled to upload code findings') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty category') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) +
         api.expect_exception('ValueError') + api.post_process(
             post_process.SummaryMarkdownRE, 'finding category is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location') +
         api.buildbucket.generic_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) +
         api.expect_exception('ValueError') + api.post_process(
             post_process.SummaryMarkdownRE, 'finding location is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location source') +
         api.buildbucket.generic_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(file_path='test-file-path',),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'location MUST specify one source') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location gerrit host') +
         api.buildbucket.generic_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=findings_pb.Location
                         .GerritChangeReference(
                             project='infra',
                             change=123456,
                             patchset=7,
                         ),
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE, 'gerrit host is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location gerrit project') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=findings_pb.Location
                         .GerritChangeReference(
                             host='chromium-review.googlesource.com',
                             change=123456,
                             patchset=7,
                         ),
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE, 'gerrit project is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location gerrit change') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=findings_pb.Location
                         .GerritChangeReference(
                             host='chromium-review.googlesource.com',
                             project='infra',
                             patchset=7,
                         ),
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE, 'gerrit change is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location gerrit patchset') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=findings_pb.Location
                         .GerritChangeReference(
                             host='chromium-review.googlesource.com',
                             project='infra',
                             change=123456,
                         ),
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'gerrit change patchset is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty location file path') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE, 'file path is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('field path should be relative') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='/test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE, 'file_path must be relative') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty start line but end line is specified') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(end_line=2,),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE,
                 'start_line is empty, implying file level comment, '
                 'but end_line is') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty start line but start column is specified') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(start_column=2,),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE,
                 'start_line is empty, implying file level comment, '
                 'but start_column is') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty start line but end column is specified') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(end_column=2,),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE,
                 'start_line is empty, implying file level comment, '
                 'but end_column is') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('negative start line') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(start_line=-1,),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'start_line MUST not be negative') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('start line specified but not end line') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(start_line=1,),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE,
                 'start_line is specified so end_line must be positive') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('negative start column') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(
                             start_line=1,
                             start_column=-1,
                             end_line=2,
                         ),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'start_column MUST not be negative') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('negative end column') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(
                             start_line=1,
                             end_line=2,
                             end_column=-1,
                         ),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'end_column MUST not be negative') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('start after end') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                         range=findings_pb.Location.Range(
                             start_line=1,
                             start_column=4,
                             end_line=1,
                             end_column=3,
                         ),
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) + api.expect_exception('ValueError') + api.post_process(
                 post_process.SummaryMarkdownRE,
                 r'\(start_line, start_column\) must be after '
                 r'\(end_line, end_column\)') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty message') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                     ),
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                 )
             ])) +
         api.expect_exception('ValueError') + api.post_process(
             post_process.SummaryMarkdownRE, 'finding message is required') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('unspecified severity level') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                 )
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'finding severity_level MUST be specified') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('empty replacement') +
         api.buildbucket.try_build(project='infra') + api.properties(
             findings_pb.Findings(findings=[
                 findings_pb.Finding(
                     category='SpellChecker',
                     location=findings_pb.Location(
                         gerrit_change_ref=gerrit_change_ref,
                         file_path='test-file-path',
                     ),
                     message='This is a typo',
                     severity_level=findings_pb.Finding.SEVERITY_LEVEL_INFO,
                     fixes=[findings_pb.Fix(description='fix desc',)])
             ])) + api.expect_exception('ValueError') +
         api.post_process(post_process.SummaryMarkdownRE,
                          'finding fix MUST contain at least 1 replacement') +
         api.post_process(post_process.DropExpectation))
