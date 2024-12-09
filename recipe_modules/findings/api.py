# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import gzip
import os

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.common.proto.findings import findings as findings_pb


class FindingsAPI(recipe_api.RecipeApi):

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._tagged_current_build = False

  # file path used in the finding location to represent commit message.
  COMMIT_MESSAGE_FILE_PATH = '/COMMIT_MSG'

  def upload_findings(
      self,
      findings: list[findings_pb.Finding],
      step_name: str | None = None,
  ) -> None:
    """Uploads code findings to ResultDB.

    Requires ResultDB to be enabled for the current Build.

    Args:
      * findings (List(findings_pb.Finding)): Code findings to upload.
        findings definition can be found in
        https://chromium.googlesource.com/infra/luci/recipes-py/+/HEAD/recipe_proto/go.chromium.org/luci/common/proto/findings/findings.proto
      * step_name (str): optional step name for uploading findings.
    """
    if not findings:
      return
    if not self.m.resultdb.enabled:
      raise ValueError("ResultDB MUST be enabled to upload code findings")
    for f in findings:
      self._validate_finding(f)

    with self.m.step.nest(
        step_name or
        f'upload {len(findings)} findings to ResultDB') as presentation:
      # TODO - crbug/382600891: update the ResultDB invocation tag instead.
      if not self._tagged_current_build:
        self.m.buildbucket.add_tags_to_current_build(
            [common_pb2.StringPair(
                key='has_code_findings',
                value='true',
            )])
        self._tagged_current_build = True
      findings = findings_pb.Findings(findings=findings)
      artifact_id = f'findings-{self.m.uuid.random()}'
      presentation.step_text = f'artifact_id: {artifact_id}'
      presentation.logs['findings.json'] = self.m.proto.encode(
          findings, 'JSONPB')
      contents = gzip.compress(self.m.proto.encode(findings, 'BINARY'), mtime=0)
      self.m.resultdb.upload_invocation_artifacts(
          {
              artifact_id: {
                  'content_type': 'application/vnd.google.protobuf+gzip',
                  'contents': contents,
              }
          },)

  def _validate_finding(self, finding: findings_pb.Finding):
    # TODO: yiwzhang - use https://github.com/bufbuild/protovalidate to
    # validate once the python wheel is available.
    if not finding.category:
      raise ValueError('finding category is required')
    if not finding.HasField('location'):
      raise ValueError('finding location is required')
    self._validate_location(finding.location)
    if not finding.message:
      raise ValueError('finding message is required')
    if not finding.severity_level or (
        finding.severity_level
        == findings_pb.Finding.SEVERITY_LEVEL_UNSPECIFIED):
      raise ValueError('finding severity_level MUST be specified')
    for fix in finding.fixes or ():
      if not fix.replacements:
        raise ValueError('finding fix MUST contain at least 1 replacement')
      for replacement in fix.replacements:
        self._validate_location(replacement.location)

  def _validate_location(self, loc: findings_pb.Location):
    if not loc.HasField('source'):
      raise ValueError('location MUST specify one source')
    if loc.gerrit_change_ref:
      if not loc.gerrit_change_ref.host:
        raise ValueError('gerrit host is required')
      if not loc.gerrit_change_ref.project:
        raise ValueError('gerrit project is required')
      if not loc.gerrit_change_ref.change:
        raise ValueError('gerrit change is required')
      if not loc.gerrit_change_ref.patchset:
        raise ValueError('gerrit change patchset is required')

    if not loc.file_path:
      raise ValueError('file path is required')
    if loc.file_path != FindingsAPI.COMMIT_MESSAGE_FILE_PATH and os.path.isabs(
        loc.file_path):
      raise ValueError(f'file_path must be relative, got {loc.file_path}')

    if loc.HasField('range'):
      if not loc.range.start_line:
        if loc.range.end_line:
          raise ValueError(f'start_line is empty, implying file level comment, '
                           f'but end_line is {loc.range.end_line} instead of 0')
        if loc.range.start_column:
          raise ValueError('start_line is empty, implying file level comment, '
                           f'but start_column is {loc.range.start_column} '
                           'instead of 0')
        if loc.range.end_column:
          raise ValueError('start_line is empty, implying file level comment, '
                           f'but end_column is {loc.range.end_column} '
                           'instead of 0')
      elif loc.range.start_line < 0:
        raise ValueError('start_line MUST not be negative, '
                         f'got {loc.range.start_line}')
      elif loc.range.end_line < 1:
        raise ValueError('start_line is specified so end_line must be '
                         f'positive, got {loc.range.end_line}')
      elif loc.range.start_column < 0:
        raise ValueError('start_column MUST not be negative, '
                         f'got {loc.range.start_column}')
      elif loc.range.end_column < 0:
        raise ValueError('end_column MUST not be negative, '
                         f'got {loc.range.end_column}')
      elif loc.range.start_line > loc.range.end_line or (
          loc.range.start_line == loc.range.end_line and
          loc.range.start_column >= loc.range.end_column and
          loc.range.end_column > 0):
        raise ValueError(
            '(start_line, start_column) must be after (end_line, end_column), '
            f'got ({loc.range.start_line}, {loc.range.start_column}) .. '
            f'({loc.range.end_line}, {loc.range.end_column})')

  def populate_source_from_current_build(
      self, location: findings_pb.Location) -> None:
    """Set the location source based on the input of the current build.

    This can be used for finding.location or replacement.location. Currently,
    only works for build with exactly one Gerrit change. Raise ValueError
    otherwise.
    """
    if not self.m.buildbucket.build:  # pragma: no cover
      raise ValueError('no current build')
    if not self.m.buildbucket.build.input:  # pragma: no cover
      raise ValueError('current build has no input')
    gerrit_changes = self.m.buildbucket.build.input.gerrit_changes
    if not gerrit_changes:
      raise ValueError('current build input does not contain a gerrit change')
    if len(gerrit_changes) > 1:
      raise ValueError('current build input contains more than one gerrit '
                       'changes')
    cl = gerrit_changes[0]
    location.gerrit_change_ref.host = cl.host
    location.gerrit_change_ref.project = cl.project
    location.gerrit_change_ref.change = cl.change
    location.gerrit_change_ref.patchset = cl.patchset
