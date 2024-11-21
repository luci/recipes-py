# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for Tricium analyzers to use.

This recipe module is intended to support different kinds of
analyzer recipes, including:
  * Recipes that wrap one or more legacy analyzers.
  * Recipes that accumulate comments one by one.
  * Recipes that wrap other tools and parse their output.
"""

import fnmatch
import gzip
import os

from google.protobuf import json_format
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.common.proto.findings import findings as findings_pb
from PB.tricium.data import Data

from . import legacy_analyzers


class TriciumApi(recipe_api.RecipeApi):
  """TriciumApi provides basic support for Tricium."""

  # Expose pre-defined analyzers, as well the LegacyAnalyzer class.
  LegacyAnalyzer = legacy_analyzers.LegacyAnalyzer
  analyzers = legacy_analyzers.Analyzers

  # The limit on the number of comments that can be added via this recipe.
  #
  # Any comments added after this threshold is reached will be dropped.
  _comments_num_limit = 1000

  def __init__(self, **kwargs):
    """Sets up the API.

    Initializes an empty list of comments for use with
    add_comment and write_comments.
    """
    super().__init__(**kwargs)
    self._comments = []
    self._findings = []

  def add_comment(
      self,
      category,
      message,
      path,
      start_line=0,
      end_line=0,
      start_char=0,
      end_char=0,
      suggestions=(),
  ):
    """Adds one comment to accumulate.

    For semantics of start_line, start_char, end_line, end_char, see Gerrit doc
    https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#comment-range
    """
    # Tricium comment
    comment = Data.Comment()
    comment.category = category
    comment.message = message
    comment.path = path
    comment.start_line = start_line
    comment.end_line = end_line
    comment.start_char = start_char
    comment.end_char = end_char

    # convert to LUCI Findings
    if not self.m.buildbucket.build.input.gerrit_changes:
      raise ValueError('missing gerrit_changes in the build input')

    cl = self.m.buildbucket.build.input.gerrit_changes[0]
    gerrit_change_ref = findings_pb.Location.GerritChangeReference(
        host=cl.host,
        project=cl.project,
        change=cl.change,
        patchset=cl.patchset,
    )
    loc = findings_pb.Location(
        gerrit_change_ref=gerrit_change_ref,
        file_path=(path or '/COMMIT_MSG'),
    )
    if start_line:
      loc.range.start_line = start_line
      loc.range.start_column = start_char
      loc.range.end_line = end_line
      loc.range.end_column = end_char
    finding = findings_pb.Finding(
        category=category,
        location=loc,
        message = message,
        severity_level=findings_pb.Finding.SEVERITY_LEVEL_WARNING,
    )

    for s in suggestions:
      json_format.ParseDict(s, comment.suggestions.add())

      # convert to LUCI Finding fixes.
      fix = finding.fixes.add(description=s.get('description', ''))
      for tr_rep in s['replacements']:
        loc = findings_pb.Location(
            gerrit_change_ref=gerrit_change_ref,
            file_path=(tr_rep['path'] or '/COMMIT_MSG'),
        )
        if tr_rep.get('start_line', 0):
          loc.range.start_line = tr_rep.get('start_line', 0)
          loc.range.start_column = tr_rep.get('start_char', 0)
          loc.range.end_line = tr_rep.get('end_line', 0)
          loc.range.end_column = tr_rep.get('end_char', 0)
        fix.replacements.add(
            location=loc,
            new_content=tr_rep['replacement'],
        )

    self.validate_comment(comment)
    self._add_comment(comment, finding)

  @staticmethod
  def validate_comment(comment):
    """Validates comment to comply with Tricium/Gerrit requirements.

    Raise ValueError on the first detected problem.
    """
    if comment.start_line < 0:
      raise ValueError('start_line must be 1-based, but %d given' %
                       (comment.start_line,))
    if comment.start_line == 0:
      for attr in ('end_line', 'start_char', 'end_char'):
        value = getattr(comment, attr)
        if value:
          raise ValueError('start_line is 0, implying file level comment, '
                           'but %s is %d instead of 0' % (attr, value))
      return
    if comment.start_line > comment.end_line and comment.end_line != 0:
      # TODO(tandrii): it's probably better to require end_line always set.
      raise ValueError('start_line must be <= end_line, but %d..%d given' %
                       (comment.start_line, comment.end_line))
    if comment.start_char < 0:
      raise ValueError('start_char must be 0-based, but %d given' %
                       (comment.start_char,))
    if comment.end_char < 0:
      raise ValueError('end_char must be 0-based, but %d given' %
                       (comment.end_char,))
    if (comment.start_line == comment.end_line and
        comment.start_char >= comment.end_char and comment.end_char > 0):
      raise ValueError(
          '(start_line, start_char) must be before (end_line, end_char), '
          'but (%d,%d) .. (%d,%d) given' % (
              comment.start_line,
              comment.start_char,
              comment.end_line,
              comment.end_char,
          ))
    if os.path.isabs(comment.path):
      raise ValueError('path must be relative to the input directory, but '
                       'got absolute path %s' % (comment.path))

  def _add_comment(self, comment, finding=None):
    if comment not in self._comments:
      self._comments.append(comment)

    if finding and finding not in self._findings:
      self._findings.append(finding)

  def write_comments(self):
    """Emit the results accumulated by `add_comment` and `run_legacy`."""
    results = Data.Results()
    results.comments.extend(self._comments)
    step = self.m.step('write results', [])
    if len(results.comments) > self._comments_num_limit:
      # We don't yet know how many of these comments are included in changed
      # lines and would be posted. Add a warning to try to help with
      # clarification in the case that Tricium unexpectedly emits no comments.
      step.presentation.status = self.m.step.WARNING
      step.presentation.step_text = (
          '%s comments created, Tricium may refuse to post comments if there '
          'are too many in changed lines. This build sends only the first %s '
          'comments.' % (len(results.comments), self._comments_num_limit))
      comments = results.comments[:self._comments_num_limit]
      del results.comments[:]
      results.comments.extend(comments)

    # The "tricium" output property is read by the Tricium service.
    step.presentation.properties['tricium'] = self.m.proto.encode(
        results, 'JSONPB', indent=0, preserving_proto_field_name=False)

    if self.m.resultdb.enabled and self._findings:
      findings = findings_pb.Findings(findings=self._findings)
      contents = gzip.compress(self.m.proto.encode(findings, 'BINARY'), mtime=0)
      self.m.resultdb.upload_invocation_artifacts(
          {
              'findings-%d' % self.m.buildbucket.build.id: {
                  'content_type': 'application/vnd.google.protobuf+gzip',
                  'contents': contents,
              },
          },
          step_name='upload findings as an invocation artifact')

    return step

  def run_legacy(self,
                 analyzers,
                 input_base,
                 affected_files,
                 commit_message,
                 emit=True):
    """Runs legacy analyzers.

    This function internally accumulates the comments from the analyzers it
    runs to the same global storage used by `add_comment()`. By default it
    emits comments from legacy analyzers to the tricium output property,
    along with any comments previously created by calling `add_comment()`
    directly, after running all the specified analyzers.

    Args:
      * analyzers (List(LegacyAnalyer)): Analyzers to run.
      * input_base (Path): The Tricium input dir, generally a checkout base.
      * affected_files (List(str)): Paths of files in the change, relative
        to input_base.
      * commit_message (str): Commit message from Gerrit.
      * emit (bool): Whether to write results to the tricium output
        property. If unset, the caller will be responsible for calling
        `write_comments` to emit the comments added by the legacy analyzers.
        This is useful for recipes that need to run a mixture of custom
        analyzers (using `add_comment()` to store comments) and legacy
        analyzers.
    """
    self._write_files_data(affected_files, commit_message, input_base)
    # For each analyzer, download the CIPD package, run it and accumulate
    # results. Note: Each analyzer could potentially be run in parallel.
    for analyzer in analyzers:
      with self.m.step.nest(analyzer.name) as presentation:
        # Check analyzer.path_filters and conditionally skip.
        if not _matches_path_filters(affected_files, analyzer.path_filters):
          presentation.step_text = 'skipped due to path filters'
        try:
          analyzer_dir = self.m.path.cleanup_dir / analyzer.name
          output_base = analyzer_dir / 'out'
          package_dir = analyzer_dir / 'package'
          self._fetch_legacy_analyzer(package_dir, analyzer)
          results = self._run_legacy_analyzer(
              package_dir,
              analyzer,
              input_dir=input_base,
              output_dir=output_base)
          # Show step results. If there are too many comments, don't include
          # them. If one analyzer fails, continue running the rest.
          for comment in results.comments:
            self._add_comment(comment)
          num_comments = len(results.comments)
          presentation.step_text = '%s comment(s)' % num_comments
          presentation.logs['result'] = self.m.proto.encode(
              results, 'JSONPB')
        except self.m.step.StepFailure:
          presentation.step_text = 'failed'
    # The tricium data dir with files.json is written in the checkout cache
    # directory and should be cleaned up.
    self.m.file.rmtree('clean up tricium data dir', input_base / 'tricium')

    if emit:
      self.write_comments()

  def _write_files_data(self, affected_files, commit_message, base_dir):
    """Writes a Files input message to a file.

    Args:
      * affected_files (List(str)): File paths. This should
        be relative to `base_dir`.
      * commit_message (str): The commit message from Gerrit.
      * base_dir (Path): Input files base directory.
    """
    files = Data.Files()
    files.commit_message = commit_message
    for path in affected_files:
      # TODO(qyearsley): Set the is_binary and status fields for each file.
      # Analyzers use these fields to determine whether to skip files.
      f = files.files.add()
      f.path = path
    data_dir = self._ensure_data_dir(base_dir)
    self.m.file.write_proto(
        'write files.json',
        data_dir / 'files.json',
        files,
        'JSONPB',
        # Tricium analyzers expect camelCase field names.
        encoding_kwargs={'preserving_proto_field_name': False})

  def _read_results(self, base_dir):
    """Reads a Tricium Results message from a file.

    Args:
      * base_dir (Path): A directory. Generally this will
        be the same as the -output arg passed to the analyzer.

    Returns: Results protobuf message.
    """
    data_dir = self._ensure_data_dir(base_dir)
    results_json = self.m.file.read_text(
        'read results',
        data_dir / 'results.json',
        test_data='{"comments":[]}')
    return json_format.Parse(results_json, Data.Results())

  def _ensure_data_dir(self, base_dir):
    """Creates the Tricium data directory if it doesn't exist.

    Simple Tricium analyzers assume that data is input/output from a
    particular subpath relative to the input/output paths passed.

    Args:
      * base_dir (Path): A directory, could be either the -input
        or -output passed to a Tricium analyzer.

    Returns: Tricium data file directory inside base_dir.
    """
    data_dir = base_dir / 'tricium' / 'data'
    self.m.file.ensure_directory('ensure tricium data dir', data_dir)
    return data_dir

  def _fetch_legacy_analyzer(self, package_dir, analyzer):
    """Fetches an analyzer package from CIPD.

    Args:
      * packages_dir (Path): The path to fetch to.
      * analyzer (LegacyAnalyzer): Analyzer package to fetch.
    """
    ensure_file = self.m.cipd.EnsureFile()
    ensure_file.add_package(analyzer.package, version=analyzer.version)
    self.m.cipd.ensure(package_dir, ensure_file)

  def _run_legacy_analyzer(self, package_dir, analyzer, input_dir, output_dir):
    """Runs a simple legacy analyzer executable and returns the results.

    Args:
      * package_dir (Path): The directory where the analyzer CIPD package
        contents have been unpacked to.
      * analyzer (LegacyAnalyzer): Analyzer object to run.
      * input_dir (Path): The Tricium input dir, which is expected to contain
        files as well as the metadata at tricium/data/files.json.
      * output_dir (Path): The directory to write results into.
    """
    # Some analyzers depend on other files in the CIPD package, so cwd is
    # expected to be the directory with the analyzer.
    with self.m.context(cwd=package_dir):
      cmd = [
          package_dir / analyzer.executable, '-input', input_dir, '-output',
          output_dir
      ] + analyzer.extra_args
      self.m.step('run analyzer',
                  cmd).presentation.logs['cmd'] = ' '.join(str(c) for c in cmd)
    return self._read_results(output_dir)


def _matches_path_filters(files, patterns):
  if len(patterns) == 0:
    return True
  for p in patterns:
    if any(fnmatch.fnmatch(f, p) for f in files):
      return True
  return False
