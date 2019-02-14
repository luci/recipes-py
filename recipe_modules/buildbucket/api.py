# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the buildbucket service.

Depends on 'buildbucket' binary available in PATH:
https://godoc.org/go.chromium.org/luci/buildbucket/client/cmd/buildbucket
"""

import base64
import json

from google.protobuf import json_format

from recipe_engine import recipe_api

from .proto import build_pb2
from .proto import common_pb2
from . import util


class BuildbucketApi(recipe_api.RecipeApi):
  """A module for interacting with buildbucket."""

  # Expose protobuf messages to the users of buildbucket module.
  build_pb2 = build_pb2
  common_pb2 = common_pb2

  def __init__(
      self, property, legacy_property, mastername, buildername, buildnumber,
      revision, parent_got_revision, branch, patch_storage, patch_gerrit_url,
      patch_project, patch_issue, patch_set, issue, patchset, *args, **kwargs):
    super(BuildbucketApi, self).__init__(*args, **kwargs)
    self._service_account_key = None
    self._host = 'cr-buildbucket.appspot.com'

    legacy_property = legacy_property or {}
    if isinstance(legacy_property, basestring):
      legacy_property = json.loads(legacy_property)
    self._legacy_property = legacy_property

    self._build = build_pb2.Build()
    if property.get('build'):
      json_format.Parse(
          json.dumps(property.get('build')),
          self._build,
          ignore_unknown_fields=True)
      self._bucket_v1 = 'luci.%s.%s' % (
          self._build.builder.project, self._build.builder.bucket)
    else:
      # Legacy mode.
      build_dict = legacy_property.get('build', {})
      self._bucket_v1 = build_dict.get('bucket', None)
      self.build.number = int(buildnumber or 0)
      self.build.created_by = build_dict.get('created_by', '')

      created_ts = build_dict.get('created_ts')
      if created_ts:
        self.build.create_time.FromDatetime(
            util.timestamp_to_datetime(float(created_ts)))

      if 'id' in build_dict:
        self._build.id = int(build_dict['id'])
      build_sets = list(util._parse_buildset_tags(build_dict.get('tags', [])))
      _legacy_builder_id(
          build_dict, mastername, buildername, self._build.builder)
      _legacy_input_gerrit_changes(
          self._build.input.gerrit_changes, build_sets, patch_storage,
          patch_gerrit_url, patch_project, patch_issue or issue,
          patch_set or patchset)
      _legacy_input_gitiles_commit(
          self._build.input.gitiles_commit, build_dict, build_sets,
          revision or parent_got_revision, branch)
      _legacy_tags(build_dict, self._build)

  def set_buildbucket_host(self, host):
    """Changes the buildbucket backend hostname used by this module.

    Args:
      host (str): buildbucket server host (e.g. 'cr-buildbucket.appspot.com').
    """
    self._host = host

  def use_service_account_key(self, key_path):
    """Tells this module to start using given service account key for auth.

    Otherwise the module is using the default account (when running on LUCI or
    locally), or no auth at all (when running on Buildbot).

    Exists mostly to support Buildbot environment. Recipe for LUCI environment
    should not use this.

    Args:
      key_path (str): a path to JSON file with service account credentials.
    """
    self._service_account_key = key_path

  @property
  def build(self):
    """Returns current build as a buildbucket.v2.Build protobuf message.

    For value format, see Build message in
    https://chromium.googlesource.com/infra/luci/luci-go/+/master/buildbucket/proto/build.proto.

    DO NOT MODIFY the returned value.
    Do not implement conditional logic on returned tags; they are for indexing.
    Use returned build.input instead.

    Pure Buildbot support: to simplify transition to buildbucket, returns a
    message even if the current build is not a buildbucket build. Provides as
    much information as possible. Some fields may be left empty, violating
    the rules described in the .proto files.
    If the current build is not a buildbucket build, returned build.id is 0.
    """
    return self._build

  @property
  def builder_name(self):
    """Returns builder name. Shortcut for .build.builder.builder."""
    return self.build.builder.builder

  @property
  def gitiles_commit(self):
    """Returns input gitiles commit. Shortcut for .build.input.gitiles_commit.

    For value format, see GitilesCommit message in
    https://chromium.googlesource.com/infra/luci/luci-go/+/master/buildbucket/proto/common.proto.

    Never returns None, but sub-fields may be empty.
    """
    return self.build.input.gitiles_commit

  @property
  def tags_for_child_build(self):
    """A dict of tags (key -> value) derived from current (parent) build for a
    child build."""
    original_tags = {t.key: t.value for t in self.build.tags}
    new_tags = {'user_agent': 'recipe'}

    # TODO(nodir): switch to ScheduleBuild API where we don't have to convert
    # build input back to tags.
    # This function returns a dict, so there can be only one buildset, although
    # we can have multiple sources.
    # Priority: CL buildset, commit buildset, custom buildset.
    commit = self.build.input.gitiles_commit
    if self.build.input.gerrit_changes:
      cl = self.build.input.gerrit_changes[0]
      new_tags['buildset'] = 'patch/gerrit/%s/%d/%d' % (
          cl.host, cl.change, cl.patchset)

    # Note: an input gitiles commit with ref without id is valid
    # but such commit cannot be used to construct a valid commit buildset.
    elif commit.host and commit.project and commit.id:
      new_tags['buildset'] = (
          'commit/gitiles/%s/%s/+/%s' % (
              commit.host, commit.project, commit.id))
      if commit.ref:
        new_tags['gitiles_ref'] = commit.ref
    else:
      buildset = original_tags.get('buildset')
      if buildset:
        new_tags['buildset'] = buildset

    if self.build.number:
      new_tags['parent_buildnumber'] = str(self.build.number)
    if self.build.builder.builder:
      new_tags['parent_buildername'] = str(self.build.builder.builder)
    return new_tags

  def set_output_gitiles_commit(self, gitiles_commit):
    """Sets buildbucket.v2.Build.output.gitiles_commit field.

    This will tell other systems, consuming the build, what version of the code
    was actually used in this build and what is the position of this build
    relative to other builds of the same builder.

    Args:
      gitiles_commit(buildbucket.common_pb2.GitilesCommit): the commit that was
        actually checked out. Must have host, project and id.
        ID must match r'^[0-9a-f]{40}$' (git revision).
        If position is present, the build can be ordered along commits.
        Position requires ref.
        Ref, if not empty, must start with "refs/".

    Can be called at most once per build.
    """
    # Validate commit object.
    c = gitiles_commit
    assert isinstance(c, common_pb2.GitilesCommit), c

    assert c.host
    assert '/' not in c.host, c.host

    assert c.project
    assert not c.project.startswith('/'), c.project
    assert not c.project.startswith('a/'), c.project
    assert not c.project.endswith('/'), c.project

    assert util.is_sha1_hex(c.id), c.id

    # position is uint32
    assert not c.position or c.ref

    assert not c.ref or c.ref.startswith('refs/'), c.ref
    assert not c.ref.endswith('/'), c.ref

    # The fact that it sets a property value is an implementation detail.
    res = self.m.step('set_output_gitiles_commit', cmd=None)
    prop_name = '$recipe_engine/buildbucket/output_gitiles_commit'
    res.presentation.properties[prop_name] = json_format.MessageToDict(
        gitiles_commit)

  # RPCs.

  def put(self, builds, **kwargs):
    """Puts a batch of builds.

    Args:
      builds (list): A list of dicts, where keys are:
        'bucket': (required) name of the bucket for the request.
        'parameters' (dict): (required) arbitrary json-able parameters that a
          build system would be able to interpret.
        'experimental': (optional) a bool indicating whether build is
          experimental. If not provided, the value will be determined by whether
          the currently running build is experimental.
        'tags': (optional) a dict(str->str) of tags for the build. These will
          be added to those generated by this method and override them if
          appropriate. If you need to remove a tag set by default, set its value
          to None (for example, tags={'buildset': None} will ensure build is
          triggered without 'buildset' tag).

    Returns:
      A step that as its .stdout property contains the response object as
      returned by buildbucket.
    """
    build_specs = []
    for build in builds:
      build_specs.append(self.m.json.dumps({
        'bucket': build['bucket'],
        'parameters_json': self.m.json.dumps(build['parameters']),
        'tags': self._tags_for_build(build['bucket'], build['parameters'],
                                     build.get('tags')),
        'experimental': build.get('experimental',
                                  self.m.runtime.is_experimental),
      }))
    return self._call_service('put', build_specs, **kwargs)

  def cancel_build(self, build_id, **kwargs):
    return self._call_service('cancel', [build_id], **kwargs)

  def get_build(self, build_id, **kwargs):
    return self._call_service('get', [build_id], **kwargs)

  # Other buildbucket tool subcommands.

  def collect_build(self, build_id, mirror_status=False, **kwargs):
    """Shorthand for collect_builds below, but for a single build only.

    Args:
      build_id: Integer ID of the build to wait for.
      mirror_status: Set step status to build status.

    Returns:
      buildbucket.v2.Build protobuf message for the ended build.
    """
    assert isinstance(build_id, int)
    build = self.collect_builds([build_id], **kwargs)[build_id]
    if mirror_status:
      self.m.step.active_result.presentation.status = {
        common_pb2.FAILURE: self.m.step.FAILURE,
        common_pb2.SUCCESS: self.m.step.SUCCESS,
      }.get(build.status, self.m.step.EXCEPTION)
    return build

  def collect_builds(
      self, build_ids, interval=60, timeout=3600, step_name=None):
    """Waits for a set of builds to end and returns their details.

    Args:
      build_ids: List of build IDs to wait for.
      interval: Delay (in secs) between requests while waiting for build to end.
      timeout: Maximum time to wait for builds to end.
      step_name: Custom name for the generated step.

    Returns:
      A map from integer build IDs to the corresponding buildbucket.v2.Build
      protobuf messages for all specified builds.
    """
    args = ['-json-output', self.m.json.output(), '-interval', '%ds' % interval]
    args += build_ids
    result = self._call_service(
        'collect', args, json_stdout=False, timeout=timeout, name=step_name)
    builds = [json_format.ParseDict(build_json, build_pb2.Build())
              for build_json in result.json.output]
    return {build.id: build for build in builds}

  # Internal.

  def _call_service(self, command, args, json_stdout=True, name=None, **kwargs):
    step_name = name or ('buildbucket.' + command)
    if self._service_account_key:
      args = ['-service-account-json', self._service_account_key] + args
    args = ['buildbucket', command, '-host', self._host] + args
    kwargs.setdefault('infra_step', True)
    stdout = self.m.json.output() if json_stdout else None
    return self.m.step(step_name, args, stdout=stdout, **kwargs)

  def _tags_for_build(self, bucket, parameters, override_tags=None):
    new_tags = self.tags_for_child_build
    builder_name = parameters.get('builder_name')
    if builder_name:
      new_tags['builder'] = builder_name
    # TODO(tandrii): remove this Buildbot-specific code.
    if bucket.startswith('master.'):
      new_tags['master'] = bucket[7:]
    new_tags.update(override_tags or {})
    return sorted(
        '%s:%s' % (k, v)
        for k, v in new_tags.iteritems()
        if v is not None)

  @property
  def bucket_v1(self):
    """Returns bucket name in v1 format.

    Mostly useful for scheduling new builds using V1 API.
    """
    return self._bucket_v1


  # DEPRECATED API.

  @property
  def properties(self):  # pragma: no cover
    """DEPRECATED, use build attribute instead."""
    return self._legacy_property

  @property
  def build_id(self):  # pragma: no cover
    """DEPRECATED, use build.id instead."""
    return self.build.id or None

  @property
  def build_input(self):  # pragma: no cover
    """DEPRECATED, use build.input instead."""
    return self.build.input

  @property
  def builder_id(self):  # pragma: no cover
    """Deprecated. Use build.builder instead."""
    return self.build.builder


# Legacy support.


def _legacy_tags(build_dict, build_msg):
  for t in build_dict.get('tags', []):
    k, v = t.split(':', 1)
    if k =='buildset' and v.startswith(('patch/gerrit/', 'commit/gitiles')):
      continue
    if k in ('build_address', 'builder'):
      continue
    build_msg.tags.add(key=k, value=v)


def _legacy_input_gerrit_changes(
    dest_repeated, build_sets,
    patch_storage, patch_gerrit_url, patch_project, patch_issue, patch_set):
  if patch_storage == 'gerrit' and patch_project:
    host, path = util.parse_http_host_and_path(patch_gerrit_url)
    if host and (not path or path == '/'):
      try:
        patch_issue = int(patch_issue or 0)
        patch_set = int(patch_set or 0)
      except ValueError:
        pass
      else:
        if patch_issue and patch_set:
          dest_repeated.add(
              host=host,
              project=patch_project,
              change=patch_issue,
              patchset=patch_set)
          return

  for bs in build_sets:
    if isinstance(bs, common_pb2.GerritChange):
      dest_repeated.add().CopyFrom(bs)


def _legacy_input_gitiles_commit(
    dest, build_dict, build_sets, revision, branch):
  commit = None
  for bs in build_sets:
    if isinstance(bs, common_pb2.GitilesCommit):
      commit = bs
      break
  if commit:
    dest.CopyFrom(commit)

    ref_prefix = 'gitiles_ref:'
    for t in build_dict.get('tags', []):
      if t.startswith(ref_prefix):
        dest.ref = t[len(ref_prefix):]
        break

    return

  if util.is_sha1_hex(revision):
    dest.id = revision
  if branch:
    dest.ref = 'refs/heads/%s' % branch


def _legacy_builder_id(build_dict, mastername, buildername, builder_id):
  builder_id.project = build_dict.get('project') or ''
  builder_id.bucket = build_dict.get('bucket') or ''

  if builder_id.bucket:
    luci_prefix = 'luci.%s.' % builder_id.project
    if builder_id.bucket.startswith(luci_prefix):
      builder_id.bucket = builder_id.bucket[len(luci_prefix):]
  if not builder_id.bucket and mastername:
    builder_id.bucket = 'master.%s' % mastername

  tags_dict = dict(t.split(':', 1) for t in build_dict.get('tags', []))
  builder_id.builder = tags_dict.get('builder') or buildername or ''
