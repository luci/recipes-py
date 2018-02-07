# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the LUCI Scheduler service.

Depends on 'prpc' binary available in $PATH:
  https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc
Documentation for scheduler API is in
  https://chromium.googlesource.com/infra/luci/luci-go/+/master/scheduler/api/scheduler/v1/scheduler.proto
RPCExplorer available at
  https://luci-scheduler.appspot.com/rpcexplorer/services/scheduler.Scheduler
"""

import collections
import uuid

from recipe_engine import recipe_api


class SchedulerApi(recipe_api.RecipeApi):
  """A module for interacting with LUCI Scheduler service."""

  def __init__(self, **kwargs):
    super(SchedulerApi, self).__init__(**kwargs)
    self._host = 'luci-scheduler.appspot.com'
    self._fake_uuid_count = 0

  def set_host(self, host):
    """Changes the backend hostname used by this module.

    Args:
      host (str): server host (e.g. 'luci-scheduler.appspot.com').
    """
    self._host = host


  class Trigger(object):
    """Generic Trigger accepted by LUCI Scheduler API.

    All supported triggers are documented here:
      https://chromium.googlesource.com/infra/luci/luci-go/+/master/scheduler/api/scheduler/v1/triggers.proto
    """
    def __init__(self, id=None, title=None, url=None, payload=None):
      self._id = id
      self._title = title
      self._url = url
      self._payload = payload

    def _serialize(self, api_self):
      t = {}
      t['id'] = self._id or api_self._next_uuid()
      t['title'] = self._title or ('%s/%s' % (
          api_self.m.properties.get('buildername'),
          api_self.m.properties.get('buildnumber')))
      # TODO(tandrii): find a way to get URL of current build.
      if self._url:
        t['url'] = self._url
      t.update(self._serialize_payload(api_self))
      return t

    def _serialize_payload(self, api_self):
      return self._payload


  class BuildbucketTrigger(Trigger):
    """Trigger with buildbucket payload for buildbucket jobs.

    Args:
      properties (dict, optional): key -> value properties.
      tags (dict, optional): additional tags on top of default ones copied from
        current build. If tag's value is None, this tag will be removed from
        resulting tags.
    """
    def __init__(self, properties=None, tags=None, **kwargs):
      super(SchedulerApi.BuildbucketTrigger, self).__init__(**kwargs)
      self._properties = properties
      self._tags = tags

    def _serialize_payload(self, api_self):
      tags = api_self.m.buildbucket.tags_for_child_build.copy()
      if self._tags:
        tags.update(self._tags)
      return {'buildbucket': {
        'properties': self._properties or {},
        'tags': map(':'.join, sorted(
            (k, v) for k, v in tags.iteritems() if v is not None)),
      }}


  class GitilesTrigger(Trigger):
    """Trigger with new Gitiles commit payload, typically for buildbucket jobs.

    Args:
      repo (str): URL of a repo that changed.
      ref (str): a ref that changed, in full, e.g. "refs/heads/master".
      revision (str): a revision (SHA1 in hex) pointed to by the ref.
    """
    def __init__(self, repo, ref, revision, **kwargs):
      kwargs['payload'] = {'gitiles': {
        'repo': repo,
        'ref': ref,
        'revision': revision,
      }}
      super(SchedulerApi.GitilesTrigger, self).__init__(**kwargs)


  def buildbucket_trigger(
      self, properties=None, tags=None,
      id=None, title=None, url=None):
    """DEPRECATED. Use BuildbucketTrigger instead."""
    # TODO(tandrii): remove this once existing callers migrate.
    return self.BuildbucketTrigger(
        properties=properties, tags=tags, id=id, title=title, url=url)

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
    https://chromium.googlesource.com/infra/luci/luci-go/+/master/scheduler/api/scheduler/v1/scheduler.proto

    Args:
      trigger_project_jobs (iterable of tuples(trigger, project, jobs)):
        each tuple corresponds to parameters of `emit_trigger` API above.
      timestamp_usec (int): unix timestamp in microseconds.
        Useful for idempotency of calls if your recipe is doing its own retries.
        https://chromium.googlesource.com/infra/luci/luci-go/+/master/scheduler/api/scheduler/v1/triggers.proto
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
    assert self.m.runtime.is_luci, 'scheduler module only works on LUCI stack'
    # TODO(tandrii): make this into standalone module.
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
      self.m.step.active_result.presentation.step_text = 'input %s' % (
          self.m.json.dumps(input_data, indent=4))

    return step_result.stdout

  def _next_uuid(self):
    if self._test_data.enabled:
      self._fake_uuid_count += 1
      return '6a0a73b0-070b-492b-9135-9f26a2a' + '%05d' % (
          self._fake_uuid_count,)
    else:  # pragma: no cover
      return str(uuid.uuid4())
