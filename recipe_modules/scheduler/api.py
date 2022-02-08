# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the LUCI Scheduler service.

Depends on 'prpc' binary available in $PATH:
  https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc
Documentation for scheduler API is in
  https://chromium.googlesource.com/infra/luci/luci-go/+/main/scheduler/api/scheduler/v1/scheduler.proto
RPCExplorer available at
  https://luci-scheduler.appspot.com/rpcexplorer/services/scheduler.Scheduler
"""

from future.utils import iteritems

import copy
import uuid

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (
    triggers as triggers_pb2)


class SchedulerApi(recipe_api.RecipeApi):
  """A module for interacting with LUCI Scheduler service."""

  def __init__(self, init_state, **kwargs):
    super(SchedulerApi, self).__init__(**kwargs)
    self._host = init_state.get('hostname') or 'luci-scheduler.appspot.com'
    self._fake_uuid_count = 0

    self._triggers = []
    for t_dict in init_state.get('triggers') or []:
      self._triggers.append(
          json_format.ParseDict(t_dict, triggers_pb2.Trigger()))

  @property
  def triggers(self):
    """Returns a list of triggers that triggered the current build.

    A trigger is an instance of triggers_pb2.Trigger.
    """
    return copy.copy(self._triggers)

  @property
  def host(self):
    """Returns the backend hostname used by this module."""
    return self._host

  def set_host(self, host):
    """Changes the backend hostname used by this module.

    Args:
      host (str): server host (e.g. 'luci-scheduler.appspot.com').
    """
    self._host = host


  class Trigger(object):
    """Generic Trigger accepted by LUCI Scheduler API.

    Don't instantiate Trigger itself. Use either BuildbucketTrigger or
    GitilesTrigger instead.

    All supported triggers are documented here:
      https://chromium.googlesource.com/infra/luci/luci-go/+/main/scheduler/api/scheduler/v1/triggers.proto
    """
    def __init__(
        self, id=None, title=None, url=None,
        properties=None, tags=None, inherit_tags=True):
      self._id = id
      self._title = title
      self._url = url
      self._properties = properties
      self._tags = tags
      self._inherit_tags = inherit_tags

    def _serialize(self, api_self):
      t = {}
      t['id'] = self._id or api_self._next_uuid()
      t['title'] = self._title or ('%s/%s' % (
          api_self.m.buildbucket.builder_name,
          api_self.m.buildbucket.build.number))
      # TODO(tandrii): find a way to get URL of current build.
      if self._url:
        t['url'] = self._url

      tags = {}
      if self._inherit_tags:
        tags = self._tags_for_child_build(api_self.m.buildbucket.build).copy()
      if self._tags:
        tags.update(self._tags)
      self._cleanup_tags(tags)
      tags = list(
          map(':'.join,
              sorted((k, v) for k, v in iteritems(tags) if v is not None)))

      base = {}
      if self._properties:
        base['properties'] = self._properties
      if tags:
        base['tags'] = tags

      t.update(self._serialize_payload(base))
      return t

    def _tags_for_child_build(self, build): # pragma: no cover
      """A dict of tags (key -> value) derived from current (parent) build for a
      child build."""
      original_tags = {
        t.key: t.value for t in build.tags
      }
      new_tags = {'user_agent': 'recipe'}
      commit = build.input.gitiles_commit
      if build.input.gerrit_changes:
        cl = build.input.gerrit_changes[0]
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

      if build.number:
        new_tags['parent_buildnumber'] = str(build.number)
      if build.builder.builder:
        new_tags['parent_buildername'] = str(build.builder.builder)
      return new_tags

    def _cleanup_tags(self, tags):
      pass

    def _serialize_payload(self, base):
      raise NotImplementedError()  # pragma: no cover


  class BuildbucketTrigger(Trigger):
    """Trigger with buildbucket payload for buildbucket jobs.

    Args:
      properties (dict, optional): key -> value properties.
      tags (dict, optional): custom tags to add. See also `inherit_tags`.
        If tag's value is None, this tag will be removed from resulting tags,
        however if you rely on this, consider using `inherit_tags=False`
        instead.
      inherit_tags (bool): if true (default), auto-adds tags using
        `api.buildbucket.tags_for_child_build` api.
    """
    def _serialize_payload(self, base):
      return {'buildbucket': base}


  class GitilesTrigger(Trigger):
    """Trigger with new Gitiles commit payload, typically for buildbucket jobs.

    Args:
      repo (str): URL of a repo that changed.
      ref (str): a ref that changed, in full, e.g. "refs/heads/main".
      revision (str): a revision (SHA1 in hex) pointed to by the ref.
      properties (dict, optional): extra key -> value properties.
      tags (dict, optional): extra custom tags to add. See also `inherit_tags`.
        If tag's value is None, this tag will be removed from resulting tags,
        however if you rely on this, consider using `inherit_tags=False`
        instead.
      inherit_tags (bool): if true (default), auto-adds extra tags using
        `api.buildbucket.tags_for_child_build` api.
    """
    def __init__(self, repo, ref, revision, **kwargs):
      super(SchedulerApi.GitilesTrigger, self).__init__(**kwargs)
      self._repo = repo
      self._ref = ref
      self._revision = revision

    def _cleanup_tags(self, tags):
      # These tags are populated based on the triggered commit by Buildbucket.
      # They could have been inherited (with wrong values) from
      # _tags_for_child_build. Drop them.
      tags.pop('buildset', None)
      tags.pop('gitiles_ref', None)

    def _serialize_payload(self, base):
      base.update({
        'repo': self._repo,
        'ref': self._ref,
        'revision': self._revision,
      })
      return {'gitiles': base}


  def emit_trigger(self, trigger, project, jobs, step_name=None):
    """Emits trigger to one or more jobs of a given project.

    Args:
      trigger (Trigger): defines payload to trigger jobs with.
      project (str): name of the project in LUCI Config service, which is used
        by LUCI Scheduler instance. See https://luci-config.appspot.com/.
      jobs (iterable of str): job names per LUCI Scheduler config for the given
        project. These typically are the same as builder names.
    """
    return self.emit_triggers([(trigger, project, jobs)], step_name=step_name)

  def emit_triggers(
      self, trigger_project_jobs, timestamp_usec=None, step_name=None):
    """Emits a batch of triggers spanning one or more projects.

    Up to date documentation is at
    https://chromium.googlesource.com/infra/luci/luci-go/+/main/scheduler/api/scheduler/v1/scheduler.proto

    Args:
      trigger_project_jobs (iterable of tuples(trigger, project, jobs)):
        each tuple corresponds to parameters of `emit_trigger` API above.
      timestamp_usec (int): unix timestamp in microseconds.
        Useful for idempotency of calls if your recipe is doing its own retries.
        https://chromium.googlesource.com/infra/luci/luci-go/+/main/scheduler/api/scheduler/v1/triggers.proto
    """
    req = {
      'batches': [
        {
          'trigger': trigger._serialize(self),
          'jobs': [{'project': project, 'job': job} for job in jobs],
        }
        for trigger, project, jobs in trigger_project_jobs
      ],
    }
    if timestamp_usec:
      assert isinstance(timestamp_usec, int), timestamp_usec
    else:
      timestamp_usec = int(self.m.time.time() * 1e6)
    req['timestamp'] = timestamp_usec

    # There is no output from EmitTriggers API.
    self._run(
        'EmitTriggers', req, step_name=step_name,
        step_test_data=lambda: self.m.json.test_api.output_stream({}))

  def _run(self, method, input_data, step_test_data=None, step_name=None):
    # TODO(tandrii): encapsulate running prpc command in a standalone module.
    step_name = step_name or ('luci-scheduler.' + method)
    args = ['prpc', 'call', '-format=json', self._host,
            'scheduler.Scheduler.' + method]
    step_result = None
    try:
      step_result = self.m.step(
          step_name,
          args,
          stdin=self.m.json.input(input_data),
          stdout=self.m.json.output(add_json_log='on_failure'),
          infra_step=True,
          step_test_data=step_test_data)
      # TODO(tandrii): add hostname to step presentation's links.
      # TODO(tandrii): handle errors nicely.
    finally:
      self.m.step.active_result.presentation.logs['input'] = self.m.json.dumps(
          input_data, indent=4).splitlines()

    return step_result.stdout

  def _next_uuid(self):
    if self._test_data.enabled:
      self._fake_uuid_count += 1
      return '6a0a73b0-070b-492b-9135-9f26a2a' + '%05d' % (
          self._fake_uuid_count,)
    else:  # pragma: no cover
      return str(uuid.uuid4())
