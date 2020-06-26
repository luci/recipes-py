# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder as builder_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2
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
      git_ref='refs/heads/master',
      revision='2d72510e447ab60a9728aeea2362d8be2cbd7789',
      build_number=0,
      build_id=8945511751514863184,
      priority=30,
      tags=None,
      status=None,
    ):
    """Returns a typical buildbucket CI build scheduled by luci-scheduler."""
    git_repo = git_repo or self._default_git_repo(project)
    gitiles_host, gitiles_project = util.parse_gitiles_repo_url(git_repo)
    if not gitiles_host or not gitiles_project:
      raise ValueError('invalid repo %s' % (git_repo,))

    build = build_pb2.Build(
        id=build_id,
        number=build_number,
        tags=tags or [],
        builder=builder_pb2.BuilderID(
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
            )),
        infra=build_pb2.BuildInfra(
            swarming=build_pb2.BuildInfra.Swarming(priority=priority),
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation='invocations/build:%d' % build_id),
        ))

    if status:
      build.status = common_pb2.Status.Value(status)

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
      git_repo=None,
      change_number=123456,
      patch_set=7,
      revision=None,
      build_number=0,
      build_id=8945511751514863184,
      priority=30,
      tags=None,
      status=None,
    ):
    """Emulate typical buildbucket try build scheduled by CQ.

    Usage:

        yield (api.test('basic') +
               api.buildbucket.try_build(project='my-proj', builder='win'))
    """
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

    build = build_pb2.Build(
        id=build_id,
        number=build_number,
        tags=tags,
        builder=builder_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ),
        created_by='user:commit-bot@chromium.org',
        create_time=timestamp_pb2.Timestamp(seconds=1527292217),
        input=build_pb2.Build.Input(gerrit_changes=[
            common_pb2.GerritChange(
                host=gerrit_host,
                project=git_project,
                change=change_number,
                patchset=patch_set,
            ),
        ]),
        infra=build_pb2.BuildInfra(
            swarming=build_pb2.BuildInfra.Swarming(priority=priority),
            resultdb=build_pb2.BuildInfra.ResultDB(
                invocation='invocations/build:%d' % build_id),
        ),
    )

    if revision:
      c = build.input.gitiles_commit
      c.host = git_host
      c.project = git_project
      c.id = revision

    if status:
      build.status = common_pb2.Status.Value(status)

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
      tags=None):
    """Emulates a generic build w/o input GitilesCommit or GerritChanges."""
    build = build_pb2.Build(
        id=build_id,
        number=build_number,
        tags=tags,
        builder=builder_pb2.BuilderID(
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
    )
    return self.build(build)


  def tags(self, **tags):
    """Alias for tags in util.py. See doc there."""
    return util.tags(**tags)

  def simulated_buildbucket_output(
      self, additional_build_parameters, step_name=None):
    """Simulates a buildbucket.get_build call."""
    step_name = step_name or 'buildbucket.get'
    buildbucket_output = {
        'build': {
            'parameters_json': json.dumps(additional_build_parameters)
        }
    }
    return self.step_data(
        step_name,
        stdout=self.m.raw_io.output_text(json.dumps(buildbucket_output)))

  def simulated_collect_output(self, builds, step_name=None):
    """Simulates a buildbucket.collect call."""
    step_name = step_name or 'buildbucket.collect'
    return self.simulated_get_multi(builds, step_name='%s.get' % step_name)

  def simulated_schedule_output(self, batch_response, step_name=None):
    """Simulates a buildbucket.schedule call."""
    return self._simulated_batch_response(
      batch_response, step_name or 'buildbucket.schedule')

  def simulated_search_results(self, builds, step_name=None):
    """Simulates a buildbucket.search call."""
    assert isinstance(builds, list), builds
    assert all(isinstance(b, build_pb2.Build) for b in builds), builds

    step_name = step_name or 'buildbucket.search'
    lines = [json.dumps(json_format.MessageToDict(b)) for b in builds]
    output = "\n".join(lines)
    return self.step_data(step_name, self.m.raw_io.stream_output(output))

  def simulated_get(self, build, step_name=None):
    """Simulates a buildbucket.get call."""
    step_name = step_name or 'buildbucket.get'
    jsonish = json_format.MessageToDict(builds_service_pb2.BatchResponse(
        responses=[dict(get_build=build)],
    ))
    return self.step_data(step_name, self.m.json.output_stream(jsonish))

  def simulated_get_multi(self, builds, step_name=None):
    """Simulates a buildbucket.get_multi call."""
    step_name = step_name or 'buildbucket.get_multi'
    jsonish = json_format.MessageToDict(builds_service_pb2.BatchResponse(
        responses=[dict(get_build=b) for b in builds],
    ))
    return self.step_data(step_name, self.m.json.output_stream(jsonish))

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
