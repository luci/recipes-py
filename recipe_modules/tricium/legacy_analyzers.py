# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Legacy analyzers which may be used by multiple projects."""

import attr
from attr.validators import instance_of
from attr.validators import matches_re
import six


@attr.s(frozen=True)
class LegacyAnalyzer(object):
  """LegacyAnalyzer is a specification for legacy "simple" Tricium analyzer.

  Legacy Tricium analyzers are executables packaged in CIPD packages.
  These executables take the flags -input and -output, in addition to other
  possible extra args:
    * `-input` specifies the root of input to read, which includes the
      tricium/data/ directory and any files to read.
    * `-output` specifies the base directory for output, and results are written
      to tricium/data/results.json relative to that directory.
  """

  # Analyzer name, for UI purposes.
  name = attr.ib(validator=instance_of(str))

  # CIPD package path.
  package = attr.ib(validator=instance_of(str))

  # Executable binary file name.
  executable = attr.ib(validator=instance_of(str))

  # CIPD package version name, defaults to "live".
  version = attr.ib(validator=instance_of(str), default='live')

  # List of path glob patterns to match, e.g. ["*.c"].
  #
  # If this is non-empty, then at least one path must match at least
  # one glob pattern for the analyzer to be run.
  path_filters = attr.ib(validator=instance_of(list), default=[])

  # List of extra arguments to add to the analyzer invocation.
  extra_args = attr.ib(validator=instance_of(list), default=[])


class Analyzers(object):
  """Specifications of common legacy analyzers.

  This is a namespace for common legacy analyzers that may be used across
  multiple projects. The source code for each of these analyzers is in the
  infra.git repo in go/src/infra/tricium/functions/; check there for
  documentation and features.
  """
  COMMITCHECK = LegacyAnalyzer(
      name='Commitcheck',
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
      name='Eslint',
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

  OBJECTIVE_C_STYLE = LegacyAnalyzer(
      name='ObjectiveCStyle',
      package='infra/tricium/function/objective-c-style',
      executable='objective-c-style',
      path_filters=['*.m', '*.mm'])

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

  @classmethod
  def by_name(self):
    """Returns a dict mapping names to LegacyAnalyzers.

    This mapping may be used to map names to analyzers, for example if a recipe
    uses strings in an input proto message to specify analyzers.
    """
    mapping = {}
    for attr in six.itervalues(self.__dict__):
      if isinstance(attr, LegacyAnalyzer):
        assert attr.name not in mapping
        mapping[attr.name] = attr
    return mapping


# This will fail if duplicate names are registered.
Analyzers.by_name()
