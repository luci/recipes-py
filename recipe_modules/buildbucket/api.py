# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the buildbucket service.

Requires `buildbucket` command in `$PATH`:
https://godoc.org/go.chromium.org/luci/buildbucket/client/cmd/buildbucket

`url_title_fn` parameter used in this module is a function that accepts a
`build_pb2.Build` and returns a link title.
If it returns `None`, the link is not reported. Default link title is build id.
"""

from future.utils import iteritems, itervalues
from past.builtins import long

from contextlib import contextmanager
from google import protobuf
from google.protobuf import field_mask_pb2
from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2
from . import util


class BuildbucketApi(recipe_api.RecipeApi):
  """A module for interacting with buildbucket."""

  HOST_PROD = 'cr-buildbucket.appspot.com'
  HOST_DEV = 'cr-buildbucket-dev.appspot.com'

  # The Build message fields that will be requested by default in buildbucket
  # rpc requests.
  DEFAULT_FIELDS = frozenset({
      'builder',
      'create_time',
      'created_by',
      'critical',
      'end_time',
      'id',
      'input',
      'number',
      'output',
      'start_time',
      'status',
      'update_time',
  })

  # Sentinel to indicate that a child build launched by `schedule_request()`
  # should use the same value as its parent for a specific attribute.
  INHERIT = object()

  def __init__(self, props, glob_props, *args, **kwargs):
    super(BuildbucketApi, self).__init__(*args, **kwargs)
    self._service_account_key = None
    self._host = props.build.infra.buildbucket.hostname or self.HOST_PROD
    self._runtime_tags = {}

    self._build = build_pb2.Build()
    if props.HasField('build'):
      self._build = props.build
      self._bucket_v1 = 'luci.%s.%s' % (
          self._build.builder.project, self._build.builder.bucket)
    else:
      # Legacy mode.
      self._bucket_v1 = None
      self.build.number = int(glob_props.buildnumber or 0)
      self.build.created_by = ''

      _legacy_builder_id(
          glob_props.mastername, glob_props.buildername, self._build.builder)
      _legacy_input_gerrit_changes(
          self._build.input.gerrit_changes, glob_props.patch_storage,
          glob_props.patch_gerrit_url, glob_props.patch_project,
          glob_props.patch_issue or glob_props.issue,
          glob_props.patch_set)
      _legacy_input_gitiles_commit(
          self._build.input.gitiles_commit,
          glob_props.revision or glob_props.parent_got_revision,
          glob_props.branch)

    self._next_test_build_id = 8922054662172514000

  @property
  def host(self):
    """Hostname of buildbucket to use in API calls.

    Defaults to the hostname that the current build is originating from.
    """
    return self._host

  @host.setter
  def host(self, value):
    self._host = value

  def set_buildbucket_host(self, host):
    """DEPRECATED. Use host property."""
    self.host = host

  @contextmanager
  def with_host(self, host):
    """Set the buildbucket host while in context, then reverts it."""
    previous_host = self.host
    try:
      self.host = host
      yield
    finally:
      self.host = previous_host

  def use_service_account_key(self, key_path):
    """Tells this module to start using given service account key for auth.

    Otherwise the module is using the default account (when running on LUCI or
    locally), or no auth at all (when running on Buildbot).

    Exists mostly to support Buildbot environment. Recipe for LUCI environment
    should not use this.

    Args:
    *  key_path (str): a path to JSON file with service account credentials.
    """
    self._service_account_key = key_path

  @property
  def build(self):
    """Returns current build as a `buildbucket.v2.Build` protobuf message.

    For value format, see `Build` message in
    [build.proto](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto).

    DO NOT MODIFY the returned value.
    Do not implement conditional logic on returned tags; they are for indexing.
    Use returned `build.input` instead.

    Pure Buildbot support: to simplify transition to buildbucket, returns a
    message even if the current build is not a buildbucket build. Provides as
    much information as possible. Some fields may be left empty, violating
    the rules described in the .proto files.
    If the current build is not a buildbucket build, returned `build.id` is 0.
    """
    return self._build

  @property
  def builder_name(self):
    """Returns builder name. Shortcut for `.build.builder.builder`."""
    return self.build.builder.builder

  @property
  def builder_realm(self):
    """Returns the LUCI realm name of the current build.

    Raises `InfraFailure` if the build proto doesn't have `project` or `bucket`
    set. This can happen in tests that don't properly mock build proto.
    """
    if not self._build.builder.project:
      raise self.m.step.InfraFailure('The build has no project')
    if not self._build.builder.bucket:  # pragma: no cover
      raise self.m.step.InfraFailure('The build has no bucket')
    return '%s:%s' % (self._build.builder.project, self._build.builder.bucket)

  def build_url(self, host=None, build_id=None):
    """Returns url to a build. Defaults to current build."""
    return 'https://%s/build/%s' % (
      host or self._host, build_id or self._build.id)

  @property
  def gitiles_commit(self):
    """Returns input gitiles commit. Shortcut for `.build.input.gitiles_commit`.

    For value format, see
    [`GitilesCommit` message](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto).

    Never returns None, but sub-fields may be empty.
    """
    return self.build.input.gitiles_commit

  def is_critical(self, build=None):
    """Returns True if the build is critical. Build defaults to the current one.
    """
    build = build or self.build
    return build.critical in (common_pb2.UNSET, common_pb2.YES)

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
    """Sets `buildbucket.v2.Build.output.gitiles_commit` field.

    This will tell other systems, consuming the build, what version of the code
    was actually used in this build and what is the position of this build
    relative to other builds of the same builder.

    Args:
    * gitiles_commit(buildbucket.common_pb2.GitilesCommit): the commit that was
      actually checked out. Must have host, project and id.
      ID must match r'^[0-9a-f]{40}$' (git revision).
      If position is present, the build can be ordered along commits.
      Position requires ref.
      Ref, if not empty, must start with `refs/`.

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

    assert c.ref.startswith('refs/'), c.ref
    assert not c.ref.endswith('/'), c.ref

    # We allow non-sha1 commits in test mode because it's convenient to set
    # commits like "branchname-HEAD-SHA" rather than inventing something which
    # looks like a git commit.
    if not self._test_data.enabled: # pragma: no cover
      assert util.is_sha1_hex(c.id), c.id

    # position is uint32
    # Does not need extra validation.

    self._build.output.gitiles_commit.CopyFrom(c)

    # The fact that it sets a property value is an implementation detail.
    res = self.m.step('set_output_gitiles_commit', cmd=None)
    prop_name = '$recipe_engine/buildbucket/output_gitiles_commit'
    res.presentation.properties[prop_name] = json_format.MessageToDict(
        gitiles_commit)

  @staticmethod
  def tags(**tags):
    """Alias for tags in util.py. See doc there."""
    return util.tags(**tags)

  def add_tags_to_current_build(self, tags):
    """Adds arbitrary tags during the runtime of a build.

    Args:
    * tags(list of common_pb2.StringPair): tags to add. May contain duplicates.
      Empty tag values won't remove existing tags with matching keys, since tags
      can only be added.
    """
    assert isinstance(tags, list), (
      'Expected type for tags is list; got %s' % type(tags))
    assert all(isinstance(tag, common_pb2.StringPair) for tag in tags), list(
        map(type, tags))

    # Multiple values for the same key are allowed in tags.
    for tag in tags:
      self._runtime_tags.setdefault(tag.key, []).append(tag.value)

    res = self.m.step('buildbucket.add_tags_to_current_build', cmd=None)
    res.presentation.properties['$recipe_engine/buildbucket/runtime-tags'] = (
      self._runtime_tags)

  def hide_current_build_in_gerrit(self):
    """Hides the build in UI"""
    self.add_tags_to_current_build(self.tags(**{'hide-in-gerrit': 'pointless'}))

  @property
  def builder_cache_path(self):
    """Path to the builder cache directory.

    Such directory can be used to cache builder-specific data.
    It remains on the bot from build to build.
    See "Builder cache" in
    https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/project_config.proto
    """
    return self.m.path['cache'].join('builder')

  # RPCs.

  def _make_field_mask(self, paths=DEFAULT_FIELDS, path_prefix=''):
    """Returns a FieldMask message to use in requests."""
    paths = set(paths)
    if 'id' not in paths:
      paths.add('id')
    return field_mask_pb2.FieldMask(
        paths=[path_prefix + p for p in sorted(paths)])

  def run(
      self, schedule_build_requests, collect_interval=None, timeout=None,
      url_title_fn=None, step_name=None, raise_if_unsuccessful=False):
    """Runs builds and returns results.

    A shortcut for schedule() and collect_builds().
    See their docstrings.

    Returns:
      A list of completed
      [Builds](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto)
      in the same order as schedule_build_requests.
    """
    with self.m.step.nest(step_name or 'buildbucket.run'):
      builds = self.schedule(
          schedule_build_requests, step_name='schedule',
           url_title_fn=url_title_fn)
      build_dict = self.collect_builds(
          [b.id for b in builds],
          interval=collect_interval,
          timeout=timeout,
          step_name='collect',
          raise_if_unsuccessful=raise_if_unsuccessful,
          # Do not print links. self.schedule printed them already.
          url_title_fn=lambda b: None,
      )
      return [build_dict[b.id] for b in builds]

  def schedule_request(
      self,
      builder,
      project=INHERIT,
      bucket=INHERIT,
      properties=None,
      experimental=INHERIT,
      experiments=None,
      gitiles_commit=INHERIT,
      gerrit_changes=INHERIT,
      tags=None,
      inherit_buildsets=True,
      swarming_parent_run_id=None,
      dimensions=None,
      priority=INHERIT,
      critical=INHERIT,
      exe_cipd_version=None,
      fields=DEFAULT_FIELDS,
  ):
    """Creates a new `ScheduleBuildRequest` message with reasonable defaults.

    This is a convenient function to create a `ScheduleBuildRequest` message.

    Among args, messages can be passed as dicts of the same structure.

    Example:

        request = api.buildbucket.schedule_request(
            builder='linux',
            tags=api.buildbucket.tags(a='b'),
        )
        build = api.buildbucket.schedule([request])[0]

    Args:
    * builder (str): name of the destination builder.
    * project (str|INHERIT): project containing the destinaiton builder.
      Defaults to the project of the current build.
    * bucket (str|INHERIT): bucket containing the destination builder.
      Defaults to the bucket of the current build.
    * properties (dict): input properties for the new build.
    * experimental (common_pb2.Trinary|INHERIT): whether the build is allowed
      to affect prod.
      Defaults to the value of the current build.
      Read more about
      [`experimental` field](https://cs.chromium.org/chromium/infra/go/src/go.chromium.org/luci/buildbucket/proto/build.proto?q="bool experimental").
    * experiments (Dict[str, bool]|None): enabled and disabled experiments
      for the new build. Overrides the result computed from experiments defined
      in builder config.
    * gitiles_commit (common_pb2.GitilesCommit|INHERIT): input commit.
      Defaults to the input commit of the current build.
      Read more about
      [`gitiles_commit`](https://cs.chromium.org/chromium/infra/go/src/go.chromium.org/luci/buildbucket/proto/build.proto?q=Input.gitiles_commit).
    * gerrit_changes (list of common_pb2.GerritChange|INHERIT): list of input
      CLs.
      Defaults to gerrit changes of the current build.
      Read more about
      [`gerrit_changes`](https://cs.chromium.org/chromium/infra/go/src/go.chromium.org/luci/buildbucket/proto/build.proto?q=Input.gerrit_changes).
    * tags (list of common_pb2.StringPair): tags for the new build.
    * inherit_buildsets (bool): if `True` (default), the returned request will
      include buildset tags from the current build.
    * swarming_parent_run_id (str|NoneType): associate the new build as child of
      the given swarming run id.
      Defaults to `None` meaning no association.
      If passed, must be a valid swarming *run* id (specific execution of a
      task) for the swarming instance on which build will execute. Typically,
      you'd want to set it to
      [`api.swarming.task_id`](https://cs.chromium.org/chromium/infra/recipes-py/recipe_modules/swarming/api.py?type=cs&q=recipe_modules/swarming/api.py+%22def+task_id%22&sq=package:chromium&g=0&l=924).
      Read more about
      [`parent_run_id`](https://cs.chromium.org/chromium/infra/go/src/go.chromium.org/luci/buildbucket/proto/rpc.proto?type=cs&q="string+parent_run_id").
    * dimensions (list of common_pb2.RequestedDimension): override dimensions
      defined on the server.
    * priority (int|NoneType|INHERIT): Swarming task priority.
      The lower the more important. Valid values are `[20..255]`.
      Defaults to the value of the current build.
      Pass `None` to use the priority of the destination builder.
    * critical (bool|common_pb2.Trinary|INHERIT): whether the build status
      should not be used to assess correctness of the commit/CL.
      Defaults to .build.critical.
      See also Build.critical in
      https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto
    * exe_cipd_version (NoneType|str|INHERIT): CIPD version of the LUCI
      Executable (e.g. recipe) to use. Pass `None` to use the server configured
      one.
    * fields (list of strs): a list of fields to include in the response, names
      relative to `build_pb2.Build` (e.g. ["tags", "infra.swarming"]).
    """

    def as_msg(value, typ):
      assert isinstance(value, (dict, protobuf.message.Message)), type(value)
      if isinstance(value, dict):
        value = typ(**value)
      return value

    def copy_msg(src, dest):
      dest.CopyFrom(as_msg(src, type(dest)))

    def as_trinary(value):
      assert isinstance(value, (bool, int))
      if isinstance(value, bool):
        value = common_pb2.YES if value else common_pb2.NO
      return value

    def if_inherit(value, parent_value):
      if value is self.INHERIT:
        return parent_value
      return value

    b = self.build

    req = builds_service_pb2.ScheduleBuildRequest(
        request_id='%d-%s' % (b.id, self.m.uuid.random()),
        builder=dict(
            project=if_inherit(project, b.builder.project),
            bucket=if_inherit(bucket, b.builder.bucket),
            builder=builder,
        ),
        priority=if_inherit(priority, b.infra.swarming.priority),
        critical=as_trinary(if_inherit(critical, b.critical)),
        # If not `INHERIT`, `experimental` must be trinary already, so only
        # pass the parent (boolean) value through `as_trinary`.
        experimental=if_inherit(experimental, as_trinary(b.input.experimental)),
        experiments=dict(experiments) if experiments else None,
        fields=self._make_field_mask(paths=fields),
    )

    if swarming_parent_run_id:
      req.swarming.parent_run_id = swarming_parent_run_id

    exe_cipd_version = if_inherit(exe_cipd_version, b.exe.cipd_version)
    if exe_cipd_version:
      req.exe.cipd_version = exe_cipd_version

    # The Buildbucket server rejects requests that have the `gitiles_commit`
    # field populated, but with all empty sub-fields. So only populate it if
    # the parent build has the field.
    gitiles_commit = if_inherit(
        gitiles_commit,
        b.input.gitiles_commit if b.input.HasField('gitiles_commit') else None)
    if gitiles_commit:
      copy_msg(gitiles_commit, req.gitiles_commit)

    for c in if_inherit(gerrit_changes, b.input.gerrit_changes):
      copy_msg(c, req.gerrit_changes.add())

    req.properties.update(properties or {})

    # Populate tags.
    tag_set = {('user_agent', 'recipe')}
    for t in tags or []:
      t = as_msg(t, common_pb2.StringPair)
      tag_set.add((t.key, t.value))

    if inherit_buildsets:
      for t in b.tags:
        if t.key == 'buildset':
          tag_set.add((t.key, t.value))

    # TODO(tandrii, nodir): find better way to communicate cq_experimental
    # status to Gerrit Buildbucket plugin.
    for t in b.tags:
      if t.key == 'cq_experimental':
        tag_set.add((t.key, t.value))

    for k, v in sorted(tag_set):
      req.tags.add(key=k, value=v)

    for d in dimensions or []:
      copy_msg(d, req.dimensions.add())

    return req

  def schedule(
      self,
      schedule_build_requests,
      url_title_fn=None,
      step_name=None,
      include_sub_invs=True):
    """Schedules a batch of builds.

    Example:
    ```python
        req = api.buildbucket.schedule_request(builder='linux')
        api.buildbucket.schedule([req])
    ```

    Hint: when scheduling builds for CQ, let CQ know about them:
    ```python
        api.cq.record_triggered_builds(*api.buildbucket.schedule([req1, req2]))
    ```

    Args:
    *   schedule_build_requests: a list of `buildbucket.v2.ScheduleBuildRequest`
        protobuf messages. Create one by calling `schedule_request` method.
    *   url_title_fn: generates a build URL title. See module docstring.
    *   step_name: name for this step.
    *   include_sub_invs: flag for including the scheduled builds' ResultDB
          invocations into the current build's invocation. Default is True.

    Returns:
      A list of
      [`Build`](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto)
      messages in the same order as requests.

    Raises:
      `InfraFailure` if any of the requests fail.
    """
    assert isinstance(schedule_build_requests, list), schedule_build_requests
    for r in schedule_build_requests:
      assert isinstance(r, builds_service_pb2.ScheduleBuildRequest), r
    if not schedule_build_requests:
      return []

    batch_req = builds_service_pb2.BatchRequest(
        requests=[dict(schedule_build=r) for r in schedule_build_requests]
    )

    test_res = builds_service_pb2.BatchResponse()
    for r in schedule_build_requests:
      test_res.responses.add(
          schedule_build=dict(
              id=self._next_test_build_id,
              builder=r.builder,
          )
      )
      self._next_test_build_id += 1

    step_res, batch_res, has_errors = self._batch_request(
        step_name or 'buildbucket.schedule', batch_req, test_res)

    sub_invocation_names = []
    # Append build links regardless of errors.
    for r in batch_res.responses:
      if not r.HasField('error'):
        self._report_build_maybe(
            step_res, r.schedule_build, url_title_fn=url_title_fn)

        inv = r.schedule_build.infra.resultdb.invocation
        if inv:
          sub_invocation_names.append(inv)

    # Include sub invocations for the successfully created builds regardless
    # of errors.
    if include_sub_invs and self.m.resultdb.enabled and sub_invocation_names:
      self.m.resultdb.include_invocations(
          invocations=self.m.resultdb.invocation_ids(sub_invocation_names),
          step_name="include sub resultdb invocations"
      )

    if has_errors:
      raise self.m.step.InfraFailure('Build creation failed')

    # Return Build messages.
    return [r.schedule_build for r in batch_res.responses]

  def _report_build_maybe(self, step_result, build, url_title_fn=None):
    """Reports a build in the step presentation.

    url_title_fn is a function that accepts a `build_pb2.Build` and returns a
    link title. If returns None, the link is not reported.
    Default link title is build id.
    """
    build_title = url_title_fn(build) if url_title_fn else build.id
    if build_title is not None:
      pres = step_result.presentation
      pres.links[str(build_title)] = self.build_url(build_id=build.id)

  def put(self, builds, **kwargs):
    """Puts a batch of builds.

    DEPRECATED. Use `schedule()` instead.

    Args:
    * builds (list): A list of dicts, where keys are:
      * 'bucket': (required) name of the bucket for the request.
      * 'parameters' (dict): (required) arbitrary json-able parameters that a
         build system would be able to interpret.
      * 'experimental': (optional) a bool indicating whether build is
         experimental. If not provided, the value will be determined by whether
         the currently running build is experimental.
      * 'tags': (optional) a dict(str->str) of tags for the build. These will
         be added to those generated by this method and override them if
         appropriate. If you need to remove a tag set by default, set its value
         to `None` (for example, `tags={'buildset': None}` will ensure build is
         triggered without `buildset` tag).

    Returns:
      A step that as its `.stdout` property contains the response object as
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
    return self._run_buildbucket('put', build_specs, **kwargs)

  def search(self,
             predicate,
             limit=None,
             url_title_fn=None,
             report_build=True,
             step_name=None,
             fields=DEFAULT_FIELDS):
    """Searches for builds.

    Example: find all builds of the current CL.

    ```python
    from PB.go.chromium.org.luci.buildbucket.proto import rpc as \
      builds_service_pb2

    related_builds = api.buildbucket.search(builds_service_pb2.BuildPredicate(
      gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),
    ))
    ```

    Args:
    *   predicate: a `builds_service_pb2.BuildPredicate` object or a list
        thereof. If a list, the predicates are connected with logical OR.
    *   limit: max number of builds to return. Defaults to 1000.
    *   url_title_fn: generates a build URL title. See module docstring.
    *   report_build: whether to report build search results in step
        presentation. Defaults to True.
    *   fields: a list of fields to include in the response, names relative
        to `build_pb2.Build` (e.g. ["tags", "infra.swarming"]).

    Returns:
      A list of builds ordered newest-to-oldest.
    """
    assert isinstance(predicate,
        (list, builds_service_pb2.BuildPredicate)), predicate
    if not isinstance(predicate, list):
      predicate = [predicate]
    assert all(
        isinstance(p, builds_service_pb2.BuildPredicate) for p in predicate)
    assert isinstance(limit, (type(None), int))
    assert limit is None or limit >= 0

    limit = limit or 1000

    args = [
      '-json',
      '-nopage',
      '-n', limit,
      '-fields', ','.join(sorted(set(fields)))]

    for p in predicate:
      args.append('-predicate')
      # Note: json.dumps produces compact JSON to reduce argument size
      args.append(self.m.json.dumps(json_format.MessageToDict(p)))

    step_result = self._run_bb(
      subcommand='ls',
      step_name=step_name or 'buildbucket.search',
      args=args,
      stdout=self.m.raw_io.output_text(add_output_log=True))

    ret = []
    # Every line is a build serialized in JSON format
    for line in step_result.stdout.splitlines():
      build = json_format.Parse(
        line, build_pb2.Build(),
        # Do not fail because recipe's proto copy is stale.
        ignore_unknown_fields=True)
      if report_build:
        self._report_build_maybe(step_result, build, url_title_fn=url_title_fn)
      ret.append(build)

      assert len(ret) <= limit, (
        'bb ls returns %d builds when limit set to %d' % (len(ret), limit))
    return ret

  def cancel_build(self, build_id, reason=' ', step_name=None):
    """Cancel the build associated with the provided build id.

    Args:
    *   `build_id` (int|str): a buildbucket build ID.
                   It should be either an integer(e.g. 123456789 or '123456789')
                   or the numeric value in string format.
    *   `reason` (str): reason for canceling the given build.
                  Can't be None or Empty. Markdown is supported.

    Returns:
      None if build is successfully canceled. Otherwise, an InfraFailure will
      be raised
    """
    self._check_build_id(build_id)
    cancel_req = builds_service_pb2.BatchRequest(
      requests=[
        dict(cancel_build=dict(
          # Expecting id to be of type int64 according to the proto definition
          id=int(build_id),
          summary_markdown=str(reason)
        ))])
    test_res = builds_service_pb2.BatchResponse(
      responses=[
        dict(cancel_build=dict(
          id=int(build_id),
          status=common_pb2.CANCELED
        ))])
    _, batch_res, has_errors = self._batch_request(
      step_name or 'buildbucket.cancel', cancel_req, test_res)

    if has_errors:
      raise self.m.step.InfraFailure(
        'Failed to cancel build [%s]. Message: %s' %(
          build_id, batch_res.responses[0].error.message))

    return None

  def get_multi(self, build_ids, url_title_fn=None, step_name=None,
                fields=DEFAULT_FIELDS):
    """Gets multiple builds.

    Args:
    *   `build_ids`: a list of build IDs.
    *   `url_title_fn`: generates build URL title. See module docstring.
    *   `step_name`: name for this step.
    *   `fields`: a list of fields to include in the response, names relative
        to `build_pb2.Build` (e.g. ["tags", "infra.swarming"]).

    Returns:
      A dict {build_id: build_pb2.Build}.
    """
    return self._get_multi(build_ids, url_title_fn, step_name, fields)[1]

  def _get_multi(self, build_ids, url_title_fn, step_name, fields):
    """Implements get_multi, but also returns StepResult."""
    batch_req = builds_service_pb2.BatchRequest(
        requests=[
          dict(get_build=dict(id=id, fields=self._make_field_mask(
              paths=fields)))
          for id in build_ids
        ],
    )
    test_res = builds_service_pb2.BatchResponse(
        responses=[
          dict(get_build=dict(id=id, status=common_pb2.SUCCESS))
          for id in build_ids
        ]
    )
    step_res, batch_res, has_errors = self._batch_request(
        step_name or 'buildbucket.get_multi', batch_req, test_res)
    ret = {}
    for res in batch_res.responses:
      if res.HasField('get_build'):
        b = res.get_build
        self._report_build_maybe(step_res, b, url_title_fn=url_title_fn)
        ret[b.id] = b
    if has_errors:
      raise self.m.step.InfraFailure('Getting builds failed')
    return step_res, ret

  def get(self, build_id, url_title_fn=None, step_name=None,
           fields=DEFAULT_FIELDS):
    """Gets a build.

    Args:
    *   `build_id`: a buildbucket build ID.
    *   `url_title_fn`: generates build URL title. See module docstring.
    *   `step_name`: name for this step.
    *   `fields`: a list of fields to include in the response, names relative
        to `build_pb2.Build` (e.g. ["tags", "infra.swarming"]).

    Returns:
      A build_pb2.Build.
    """
    builds = self.get_multi(
        [build_id],
        url_title_fn=url_title_fn,
        step_name=step_name or 'buildbucket.get',
        fields=fields)
    return builds[build_id]

  def get_build(self, build_id, **kwargs):
    """DEPRECATED. Use get()."""
    return self._run_buildbucket('get', [build_id], **kwargs)

  def collect_build(self, build_id, **kwargs):
    """Shorthand for `collect_builds` below, but for a single build only.

    Args:
    * build_id: Integer ID of the build to wait for.

    Returns:
      [Build](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto).
      for the ended build.
    """
    assert isinstance(build_id, int)
    return self.collect_builds([build_id], **kwargs)[build_id]

  def collect_builds(
      self, build_ids, interval=None, timeout=None, step_name=None,
      raise_if_unsuccessful=False, url_title_fn=None,
      mirror_status=False, fields=DEFAULT_FIELDS,
  ):
    """Waits for a set of builds to end and returns their details.

    Args:
    * `build_ids`: List of build IDs to wait for.
    * `interval`: Delay (in secs) between requests while waiting for build to
      end. Defaults to 1m.
    * `timeout`: Maximum time to wait for builds to end. Defaults to 1h.
    * `step_name`: Custom name for the generated step.
    * `raise_if_unsuccessful`: if any build being collected did not succeed,
      raise an exception.
    * `url_title_fn`: generates build URL title. See module docstring.
    * `mirror_status`: mark the step as failed/infra-failed if any of the builds
      did not succeed. Ignored if raise_if_unsuccessful is True.
    * `fields`: a list of fields to include in the response, names relative
      to `build_pb2.Build` (e.g. ["tags", "infra.swarming"]).

    Returns:
      A map from integer build IDs to the corresponding
      [Build](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto)
      for all specified builds.
    """
    if not build_ids:
      return {}
    interval = interval or 60
    timeout = timeout or 3600

    with self.m.step.nest(step_name or 'buildbucket.collect'):
      # Wait for the builds to finish.
      self._run_bb(
          step_name='wait',
          subcommand='collect',
          args=['-interval', '%ds' % interval] + build_ids,
          timeout=timeout,
      )

      # Fetch build details.
      if raise_if_unsuccessful or mirror_status:
        if fields and 'status' not in fields:
          fields = fields[:]
          fields.append('status')
      step_res, builds = self._get_multi(
          build_ids, url_title_fn=url_title_fn, step_name='get', fields=fields)

      if raise_if_unsuccessful:
        unsuccessful_builds = sorted(
            b.id for b in itervalues(builds)
            if b.status != common_pb2.SUCCESS
        )
        if unsuccessful_builds:
          step_res.presentation.status = self.m.step.FAILURE
          step_res.presentation.logs['unsuccessful_builds'] = [
              str(b) for b in unsuccessful_builds]
          raise self.m.step.InfraFailure(
              'Triggered build(s) did not succeed, unexpectedly')
      elif mirror_status:
        bs = list(itervalues(builds))
        if any(b.status == common_pb2.INFRA_FAILURE for b in bs):
          step_res.presentation.status = self.m.step.EXCEPTION
        elif any(b.status == common_pb2.FAILURE for b in bs):
          step_res.presentation.status = self.m.step.FAILURE

      return builds

  # Internal.

  def _batch_request(self, step_name, request, test_response):
    """Makes a Builds.Batch request.

    Returns (StepResult, builds_service_pb2.BatchResponse, has_errors) tuple.
    """
    request_dict = json_format.MessageToDict(request)
    try:
      self._run_bb(
          step_name=step_name,
          subcommand='batch',
          stdin=self.m.json.input(request_dict),
          stdout=self.m.json.output(),
          step_test_data=lambda: self.m.json.test_api.output_stream(
              json_format.MessageToDict(test_response)
          ),
      )
    except self.m.step.StepFailure:  # pragma: no cover
      # Ignore the exit code and parse the response as BatchResponse.
      # Fail if parsing fails.
      pass

    step_res = self.m.step.active_result

    # Log the request.
    step_res.presentation.logs['request'] = self.m.json.dumps(
        request_dict, indent=2, sort_keys=True).splitlines()

    # Parse the response.
    if step_res.stdout is None:
      raise self.m.step.InfraFailure('Buildbucket Internal Error')
    batch_res = builds_service_pb2.BatchResponse()
    json_format.ParseDict(
        step_res.stdout, batch_res,
        # Do not fail the build because recipe's proto copy is stale.
        ignore_unknown_fields=True)

    # Print response errors in step text.
    step_text = []
    has_errors = False
    for i, r in enumerate(batch_res.responses):
      if r.HasField('error'):
        has_errors = True
        step_text.extend([
            'Request #%d' % i,
            'Status code: %s' % r.error.code,
            'Message: %s' % r.error.message,
            '',  # Blank line.
        ])
    step_res.presentation.step_text = '<br>'.join(step_text)

    return (step_res, batch_res, has_errors)

  def _run_bb(
      self, subcommand, step_name=None, args=None, stdin=None, stdout=None,
      step_test_data=None, timeout=None):
    cmdline = [
      'bb', subcommand,
      '-host', self._host,
    ]
    # Do not pass -service-account-json. It is not needed on LUCI.
    # TODO(nodir): change api.runtime.is_luci default to True and assert
    # it is true here.
    cmdline += args or []

    return self.m.step(
        step_name or ('bb ' + subcommand),
        cmdline,
        infra_step=True,
        stdin=stdin,
        stdout=stdout,
        step_test_data=step_test_data,
        timeout=timeout,
    )

  # TODO(nodir): remove in favor of _run_bb
  def _run_buildbucket(
      self, subcommand, args=None, json_stdout=True, name=None, **kwargs):
    step_name = name or ('buildbucket.' + subcommand)

    args = args or []
    if self._service_account_key:
      args = ['-service-account-json', self._service_account_key] + args
    args = ['buildbucket', subcommand, '-host', self._host] + args

    kwargs.setdefault('infra_step', True)
    stdout = self.m.json.output() if json_stdout else None
    return self.m.step(step_name, args, stdout=stdout, **kwargs)

  def _tags_for_build(self, bucket, parameters, override_tags=None):
    new_tags = self.tags_for_child_build
    builder_name = parameters.get('builder_name')
    if builder_name:
      new_tags['builder'] = builder_name
    new_tags.update(override_tags or {})
    return sorted(
        '%s:%s' % (k, v)
        for k, v in iteritems(new_tags)
        if v is not None)

  def _check_build_id(self, build_id):
    """Raise ValueError if the given build id is not a number or a string
    that represents numeric value.
    """
    is_int = isinstance(build_id, (int, long))
    is_str_num = isinstance(build_id, str) and build_id.isdigit()
    if not (is_int or is_str_num):
      raise ValueError('Expected a numeric build id, got %s' %(build_id,))

  @property
  def bucket_v1(self):
    """Returns bucket name in v1 format.

    Mostly useful for scheduling new builds using V1 API.
    """
    return self._bucket_v1


  # DEPRECATED API.

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


def _legacy_input_gerrit_changes(
    dest_repeated,
    patch_storage, patch_gerrit_url, patch_project, patch_issue, patch_set):
  if patch_storage == 'gerrit' and patch_project:
    host, path = util.parse_http_host_and_path(patch_gerrit_url)
    if host and (not path or path == '/'):
      try:
        patch_issue = int(patch_issue or 0)
        patch_set = int(patch_set or 0)
      except ValueError:  # pragma: no cover
        pass
      else:
        if patch_issue and patch_set:
          dest_repeated.add(
              host=host,
              project=patch_project,
              change=patch_issue,
              patchset=patch_set)
          return


def _legacy_input_gitiles_commit(dest, revision, branch):
  if util.is_sha1_hex(revision):
    dest.id = revision
  if branch:
    dest.ref = 'refs/heads/%s' % branch


def _legacy_builder_id(mastername, buildername, builder_id):
  if mastername:
    builder_id.bucket = 'master.%s' % mastername
  builder_id.builder = buildername or ''
