# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Legacy analyzers which may be used by multiple projects."""

import attr
from attr.validators import instance_of
from attr.validators import matches_re


@attr.s(frozen=True)
class LegacyAnalyzer(object):
  """LegacyAnalyzer is a specification for legacy "simple" Tricium analyzer.

  In the initial design, Tricium analyzers were in CIPD packages, and analyzers
  would be triggered by directly triggering Swarming tasks. Such analyzers are
  programs (in practice, all written in Go) which took the flags -input and
  -output:
    * `-input` specifies the root of input to read, which includes the
      tricium/data/ directory and any files to read.
    * `-output` specifies the base directory for output, and results are written
    to tricium/data/results.json relative to that directory.
  """

  # Analyzer name, for UI purposes.
  name = attr.ib(validator=instance_of(str))

  # CIPD package path and version.
  package = attr.ib(validator=instance_of(str))

  # Executable binary name.
  executable = attr.ib(validator=instance_of(str))

  # CIPD package version name. Generally "live" but it's possible to use
  # another one.
  version = attr.ib(validator=instance_of(str), default='live')

  # List of path patterns to match.
  #
  # If this is non-empty, then at least one path must match at least
  # one glob pattern for the analyzer to be run.
  path_filters = attr.ib(validator=instance_of(list), default=[])

  # List of args to add to the analyzer invocation.
  extra_args = attr.ib(validator=instance_of(list), default=[])


class Analyzers(object):
  """Specifications of common legacy analyzers.

  This is a namespace for common CIPD-package-based analyzers that may be used
  across multiple projects. The source code for each of these analyzers is in
  the infra.git repo in go/src/infra/tricium/functions/; check there for
  documentation and features.
  """
  COMMITCHECK = LegacyAnalyzer(
      name='CommitCheck',
      package='infra/tricium/function/commitcheck',
      executable='commitcheck')

  COPYRIGHT = LegacyAnalyzer(
      name='Copyright',
      package='infra/tricium/function/copyright',
      executable='copyright',
      path_filters=[
          '*.c',
          '*.cc',
          '*.cpp',
          '*.go',
          '*.h',
          '*.java',
          '*.js',
          '*.py',
          '*.sh',
      ])

  CPPLINT = LegacyAnalyzer(
      name='Cpplint',
      package='infra/tricium/function/cpplint',
      executable='cpplint_parser',
      path_filters=['*.cc', '*.cpp', '*.cu', '*.cuh', '*.h'],
      extra_args=['-filter=-whitespace,-build/header_guard', '-verbose=4'])

  ESLINT = LegacyAnalyzer(
      name='ESlint',
      package='infra/tricium/function/eslint',
      executable='eslint_parser',
      path_filters=['*.js'])

  GOSEC = LegacyAnalyzer(
      name='Gosec',
      package='infra/tricium/function/eslint',
      executable='gosec_wrapper',
      path_filters=['*.go'])

  HTTPS_CHECK = LegacyAnalyzer(
      name='HttpsCheck',
      package='infra/tricium/function/https-check',
      executable='https-check')

  MOJOM_COMMENTATOR = LegacyAnalyzer(
      name='MojomCommentator',
      package='infra/tricium/function/mojom-commentator',
      executable='mojom-commentator',
      path_filters=['*.mojom'])

  PYLINT = LegacyAnalyzer(
      name='Pylint',
      package='infra/tricium/function/pylint',
      executable='pylint_wrapper',
      path_filters=['*.py'])

  SPELLCHECKER = LegacyAnalyzer(
      name='Spellchecker',
      package='infra/tricium/function/spellchecker',
      executable='spellchecker')

  SPACEY = LegacyAnalyzer(
      name='Spacey',
      package='infra/tricium/function/spacey',
      executable='spacey')
