# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime
import json
from typing import Sequence

from google.protobuf import duration_pb2
from google.protobuf import json_format
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import task as task_pb2
from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from . import util


class BuildbucketTestApi(recipe_test_api.RecipeTestApi):
  def build(self, build_message):
    """Emulates a buildbucket build.

    build_message is a buildbucket.build_pb2.Build.
    """
    ret = self.test(None)
    ret.properties.update(**{
      '$recipe_engine/buildbucket': {
        'build': json.loads(json_format.MessageToJson(build_message)),
      },
    })

    # Mock luci_context based on the build info.
    realm_ctx = sections_pb2.Realm(name='%s:%s' % (
        build_message.builder.project, build_message.builder.bucket))
    rdb_ctx = sections_pb2.ResultDB(
        current_invocation=sections_pb2.ResultDBInvocation(
            name=build_message.infra.resultdb.invocation,
            update_token='token',
        ),
        hostname='rdbhost',
    )
    ret.luci_context.update({
        'realm': json_format.MessageToDict(realm_ctx),
        'resultdb': json_format.MessageToDict(rdb_ctx),
    })
    return ret

  def _default_git_repo(self, project):  # pragma: no cover
    if 'internal' in project:
      return 'https://chrome-internal.googlesource.com/' + project
    return 'https://chromium.googlesource.com/' + project

  def ci_build_message(
      self,
      project='project',
      bucket='ci',  # shortname.
      builder='builder',
      git_repo=None,
      git_ref='refs/heads/main',
      revision='2d72510e447ab60a9728aeea2362d8be2cbd7789',
      build_number=0,
      build_id=8945511751514863184,
      priority=30,
      tags=None,
      status=None,
      experiments=(),
      exe=None,
      execution_timeout=None,
      start_time=None,
      on_backend=False,
  ):
    """Returns a typical buildbucket CI build scheduled by luci-scheduler."""
    git_repo = git_repo or self._default_git_repo(project)
    gitiles_host, gitiles_project = util.parse_gitiles_repo_url(git_repo)
    if not gitiles_host or not gitiles_project:
      raise ValueError('invalid repo %s' % (git_repo,))

    infra = build_pb2.BuildInfra(
        swarming=build_pb2.BuildInfra.Swarming(priority=priority),
        resultdb=build_pb2.BuildInfra.ResultDB(
            invocation='invocations/build:%d' % build_id),
    )
    if on_backend:
      backend_config_dict = {'priority': priority}
      infra = build_pb2.BuildInfra(
          backend=build_pb2.BuildInfra.Backend(
              config=self.dict_to_struct(backend_config_dict),
              task=task_pb2.Task(id=task_pb2.TaskID())),
          resultdb=build_pb2.BuildInfra.ResultDB(
              invocation='invocations/build:%d' % build_id),
      )

    build = build_pb2.Build(
        id=build_id,
        number=build_number,
        tags=tags or [],
        builder=builder_common_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
        created_by='user:luci-scheduler@appspot.gserviceaccount.com',
        create_time=timestamp_pb2.Timestamp(seconds=1527292217),
        input=build_pb2.Build.Input(
            gitiles_commit=common_pb2.GitilesCommit(
                host=gitiles_host,
                project=gitiles_project,
                ref=git_ref,
                id=revision,
            ),
            experiments=experiments),
        infra=infra)

    if execution_timeout:
      build.execution_timeout.FromSeconds(execution_timeout)

    if start_time:
      assert isinstance(start_time, datetime.datetime), start_time
      build.start_time.FromDatetime(start_time)

    if status:
      build.status = common_pb2.Status.Value(status)

    if exe:
      build.exe.CopyFrom(exe)

    return build

  def ci_build(self, *args, **kwargs):
    """Returns a typical buildbucket CI build scheduled by luci-scheduler.

    A shortcut for api.buildbucket.build(api.buildbucket.ci_build_message()).

    Usage:
        yield (api.test('basic') +
               api.buildbucket.ci_build(project='my-proj', builder='win'))
    """
    return self.build(self.ci_build_message(*args, **kwargs))

  def try_build_message(
      self,
      project='project',
      bucket='try',  # shortname.
      builder='builder',
      gerrit_changes=None,
      git_repo=None,
      git_ref='refs/heads/main',
      change_number=123456,
      patch_set=7,
      revision=None,
      build_number=0,
      build_id=8945511751514863184,
      critical='UNSET',  # other accepted values are ['YES', 'NO']
      priority=30,
      created_by=None,
      tags=None,
      status=None,
      experiments=(),
      exe=None,
      execution_timeout=None,
      start_time=None,
      properties=None,
      on_backend=False,
  ):
    """Emulate typical buildbucket try build scheduled by CQ.

    Usage:

        yield (api.test('basic') +
               api.buildbucket.try_build(project='my-proj', builder='win'))
    """
    if created_by is None:
      created_by = 'project:' + project
    git_repo = git_repo or self._default_git_repo(project)
    git_host, git_project = util.parse_gitiles_repo_url(git_repo)

    gerrit_host = git_host
    gs_suffix = '.googlesource.com'
    if gerrit_host.endswith(gs_suffix):
      prefix = gerrit_host[:-len(gs_suffix)]
      if not prefix.endswith('-review'):
        gerrit_host = '%s-review%s' % (prefix, gs_suffix)

    tags = list(tags) if tags else []
    # CQ always sets "cq_experimental:" tag, which is then used by Gerrit
    # Buildbucket plugin to hide "cq_experimental:true" builds.
    if all(t.key != 'cq_experimental' for t in tags):
      tags.append(common_pb2.StringPair(key='cq_experimental', value='false'))

    if gerrit_changes is None:
      gerrit_changes = [
          common_pb2.GerritChange(
              host=gerrit_host,
              project=git_project,
              change=change_number,
              patchset=patch_set,
          ),
      ]

    infra = build_pb2.BuildInfra(
        swarming=build_pb2.BuildInfra.Swarming(priority=priority),
        resultdb=build_pb2.BuildInfra.ResultDB(
            invocation='invocations/build:%d' % build_id),
    )
    if on_backend:
      backend_config_dict = {'priority': priority}
      infra = build_pb2.BuildInfra(
          backend=build_pb2.BuildInfra.Backend(
              config=self.dict_to_struct(backend_config_dict),
              task=task_pb2.Task(id=task_pb2.TaskID())),
          resultdb=build_pb2.BuildInfra.ResultDB(
              invocation='invocations/build:%d' % build_id),
      )

    build = build_pb2.Build(
        id=build_id,
        number=build_number,
        tags=tags,
        builder=builder_common_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
        created_by=created_by,
        create_time=timestamp_pb2.Timestamp(seconds=1527292217),
        critical=common_pb2.Trinary.Value(critical),
        input=build_pb2.Build.Input(
            gerrit_changes=gerrit_changes,
            experiments=experiments,
            properties=properties),
        infra=infra,
    )

    if execution_timeout:
      build.execution_timeout.FromSeconds(execution_timeout)

    if start_time:
      assert isinstance(start_time, datetime.datetime), start_time
      build.start_time.FromDatetime(start_time)

    if revision:
      c = build.input.gitiles_commit
      c.host = git_host
      c.project = git_project
      c.ref = git_ref
      c.id = revision

    if status:
      build.status = common_pb2.Status.Value(status)

    if exe:
      build.exe.CopyFrom(exe)

    return build

  def try_build(self, *args, **kwargs):
    """Emulates a typical buildbucket try build scheduled by CQ.

    Shortcut for api.buildbucket.build(api.buildbucket.try_build_message()).

    Usage:

        yield (api.test('basic') +
               api.buildbucket.try_build(project='my-proj', builder='win'))
    """
    return self.build(self.try_build_message(*args, **kwargs))

  def generic_build(
      self,
      project='project',
      bucket='cron',  # shortname.
      builder='builder',
      build_number=0,
      build_id=8945511751514863184,
      priority=30,
      tags=None,
      experiments=()):
    """Emulates a generic build w/o input GitilesCommit or GerritChanges."""
    build = build_pb2.Build(
        id=build_id,
        number=build_number,
        tags=tags,
        builder=builder_common_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
        created_by='user:user@example.com',
        create_time=timestamp_pb2.Timestamp(seconds=1527292217),
        infra=build_pb2.BuildInfra(
            swarming=build_pb2.BuildInfra.Swarming(priority=priority),
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation='invocations/build:%d' % build_id),
        ),
        input=build_pb2.Build.Input(experiments=experiments),
    )
    return self.build(build)

  def backend_build_message(
      self,
      project='project',
      bucket='try',
      builder='builder-backend',
      build_id=8945511751514863184,
      tags=None,
      status=None,
      task=None,
      task_dimensions=None,
      backend_hostname=None,
      backend_config=None,
  ):
    """Emulates a typical buildbucket backend build.
      Usage:

          yield (api.test('basic') +
                api.buildbucket.backend_build(
                  project='my-proj',
                  builder='win',
                  task=task_pb2.Task(
                      id=task_pb2.TaskID(
                          id="1",
                          target="swarming://chromium-swarm"
                      )
                  ),
                  backend_hostname="some_server"
              ))
      """
    return self.build(
        self.backend_build(project, bucket, builder, build_id, tags, status,
                           task, task_dimensions, backend_hostname,
                           backend_config))

  def backend_build(
      self,
      project='project',
      bucket='try',
      builder='builder-backend',
      build_id=8945511751514863184,
      tags=None,
      status=None,
      task=None,
      task_dimensions=None,
      backend_hostname=None,
      backend_config=None,
  ):
    return build_pb2.Build(
        id=build_id,
        tags=tags,
        status=status,
        builder=builder_common_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
        infra=build_pb2.BuildInfra(
            backend=build_pb2.BuildInfra.Backend(
                task=task,
                task_dimensions=task_dimensions,
                hostname=backend_hostname,
                config=backend_config,
            ),
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation='invocations/build:%d' % build_id),
        ),
    )

  def raw_swarming_build_message(
      self,
      project='project',
      bucket='try',
      builder='builder-backend',
      build_id=8945511751514863184,
      tags=None,
      status=None,
      priority=None,
      task_dimensions=None,
      hostname=None,
      bot_dimensions=None,
      task_id=None,
      parent_run_id=None,
      task_service_account=None,
  ):
    return self.build(
        self.raw_swarming_build(project, bucket, builder, build_id, tags,
                                status, priority, task_dimensions, hostname,
                                bot_dimensions, task_id, parent_run_id,
                                task_service_account))

  def raw_swarming_build(
      self,
      project='project',
      bucket='try',
      builder='builder-backend',
      build_id=8945511751514863184,
      tags=None,
      status=None,
      priority=None,
      task_dimensions=None,
      hostname=None,
      bot_dimensions=None,
      task_id=None,
      parent_run_id=None,
      task_service_account=None,
  ):
    return build_pb2.Build(
        id=build_id,
        tags=tags,
        status=status,
        builder=builder_common_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
        infra=build_pb2.BuildInfra(
            swarming=build_pb2.BuildInfra.Swarming(
                hostname=hostname,
                priority=priority,
                task_id=task_id,
                parent_run_id=parent_run_id,
                task_service_account=task_service_account,
                task_dimensions=task_dimensions,
                bot_dimensions=bot_dimensions,
            ),
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation='invocations/build:%d' % build_id),
        ),
    )

  def tags(self, **tags):
    """Alias for tags in util.py. See doc there."""
    return util.tags(**tags)

  def dict_to_struct(self, d):
    return json_format.Parse(json.dumps(d), struct_pb2.Struct())

  def extend_swarming_bot_dimensions(self, build, new_dims):
    """Extends swarming dimensions of a build.
    build: build_pb2.Build. The build to be modified.
    newDims: Dict. The dimensions to add.

    Returns: build_pb2.Build

    Usage should look like

    b = api.buildbucket.backend_build(...)
    b = api.buildbucket.extend_swarming_bot_dimensions(b, {
        "key1": "value1",
        "key2": ["value2", "value3"]
    })
    """
    if len(build.infra.swarming.bot_dimensions) > 0:
      build.infra.swarming.bot_dimensions.extend(self.tags(**new_dims))
      return build
    updated_dims = dict()
    task_details = build.infra.backend.task.details
    for k, v in task_details['bot_dimensions'].items():
      updated_dims[k] = list(v)
    for k, v in new_dims.items():
      if not isinstance(v, list):
        new_dims[k] = [v]
    updated_dims.update(new_dims)
    task_details_dict = {"bot_dimensions": updated_dims}
    build.infra.backend.task.details.update(task_details_dict)
    return build

  def exe(self, cipd_pkg, cipd_ver=None, cmd=None):
    """Emulates a build executable."""
    return common_pb2.Executable(
      cipd_package=cipd_pkg,
      cipd_version=cipd_ver,
      cmd=cmd,
    )

  def simulated_collect_output(self, builds, step_name=None):
    """Simulates a buildbucket.collect call."""
    step_name = step_name or 'buildbucket.collect'
    return self.simulated_get_multi(builds, step_name='%s.get' % step_name)

  def simulated_schedule_output(self, batch_response, step_name=None):
    """Simulates a buildbucket.schedule call."""
    return self._simulated_batch_response(
      batch_response, step_name or 'buildbucket.schedule')

  def simulated_search_result_data(self, builds):
    """Simulates buildbucket.search results."""
    assert isinstance(builds, Sequence), builds
    for b in builds:
      assert isinstance(b, build_pb2.Build), b

    lines = [
        json.dumps(json_format.MessageToDict(b), sort_keys=True) for b in builds
    ]
    return self.m.raw_io.stream_output_text("\n".join(lines))

  def simulated_search_results(self, builds, step_name=None):
    """Simulates a buildbucket.search call."""
    assert isinstance(builds, list), builds
    return self.step_data(step_name or 'buildbucket.search',
                          self.simulated_search_result_data(builds))

  def simulated_list_builders(self, builders, step_name=None):
    """Simulates a buildbucket.builders call."""
    assert isinstance(builders, list), builders
    assert all(isinstance(b, str) for b in builders), builders

    step_name = step_name or 'buildbucket.builders'
    output = "\n".join(builders)
    return self.step_data(step_name, self.m.raw_io.stream_output_text(output))

  def simulated_get(self, build, step_name=None):
    """Simulates a buildbucket.get call."""
    return self._simulated_batch_response(
        builds_service_pb2.BatchResponse(responses=[dict(get_build=build)]),
        step_name or 'buildbucket.get')

  def simulated_get_multi(self, builds, step_name=None):
    """Simulates a buildbucket.get_multi call."""
    return self._simulated_batch_response(
        builds_service_pb2.BatchResponse(
            responses=[dict(get_build=b) for b in builds],
        ),
        step_name or 'buildbucket.get_multi')

  def simulated_cancel_output(self, batch_response, step_name=None):
    """Simulates a buildbucket.cancel call"""
    return self._simulated_batch_response(
      batch_response, step_name or 'buildbucket.cancel')

  def _simulated_batch_response(self, batch_response, step_name):
    """Simulate that the given step will write the provided batch response into
    step data. The return code will be 1 for step data if the responses contain
    error. Otherwise, 0
    """
    assert isinstance(batch_response, builds_service_pb2.BatchResponse)
    ret_code = int(any(r.HasField('error') for r in batch_response.responses))
    jsonish = json_format.MessageToDict(batch_response)
    return self.step_data(
        step_name, self.m.json.output_stream(jsonish, retcode=ret_code))
