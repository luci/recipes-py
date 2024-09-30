# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""An interface to call the led tool."""

from urllib.parse import urlparse

import attr

from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb
from PB.go.chromium.org.luci.led.job import job


class LedApi(recipe_api.RecipeApi):
  """Interface to the led tool.

  "led" stands for LUCI editor. It allows users to debug and modify LUCI jobs.
  It can be used to modify many aspects of a LUCI build, most commonly
  including the recipes used.

  The main interface this module provides is a direct call to the led binary:

    led_result = api.led(
      'get-builder', ['luci.chromium.try:chromium_presubmit'])
    final_data = led_result.then('edit-recipe-bundle').result

  See the led binary for full documentation of commands.
  """

  @attr.s(frozen=True, slots=True)
  class LedLaunchData:
    buildbucket_hostname = attr.ib()
    build_id = attr.ib()

    @property
    def build_url(self):
      if not self.build_id:  # pragma: no cover
        return None
      return 'https://%s/build/%s' % (self.buildbucket_hostname, self.build_id)

  class LedResult:
    """Holds the result of a led operation. Can be chained using |then|."""

    def __init__(self, result, module):
      if isinstance(result, LedApi.LedLaunchData):
        self._launch_result = result
        self._result = result
        self._module = None
      else:
        self._launch_result = None
        self._result = result
        self._module = module

    @property
    def result(self):
      """The mutable job.Definition proto message from the previous led call.

      If the previous led call was `launch`, then this will be None, and
      launch_result will be populated.
      """
      return self._result

    @property
    def launch_result(self):
      """A LedLaunchData object. Only set when the previous led call was
      'led launch'."""
      return self._launch_result

    @property
    def edit_rbh_value(self):
      """Returns either the user_payload or cas_user_payload value suitable to
      pass to `led edit -rbh`.

      Returns `None` if this information is not set.
      """
      r = self._result
      if r:
        agent = r.buildbucket.bbagent_args.build.infra.buildbucket.agent
        if agent:
          for d, purpose in agent.purposes.items():
            if (purpose ==
                build_pb.BuildInfra.Buildbucket.Agent.PURPOSE_EXE_PAYLOAD):
              if agent.input.data.get(d):
                cas = agent.input.data[d].cas
                if cas:
                  return "%s/%d" % (cas.digest.hash, cas.digest.size_bytes)

    def with_injected_input_recipes(self, use_payload=False):
      """Sets the version of recipes used by led to correspond to the version
      currently being used.

      If neither the `rbe_cas_input` nor the `cipd_input` property is set,
      this is a no-op.

      Args:
      * use_payload - Use edit-payload or edit -rbh to update cas input.

      Returns another LedResult object with the output of the command.
      """
      if self._module.rbe_cas_input:
        if use_payload:
          return self.then(
              'edit-payload', '-cas-ref',
              '%s/%s' % (self._module.rbe_cas_input.digest.hash,
                         self._module.rbe_cas_input.digest.size_bytes))
        else:
          return self.then(
              'edit', '-rbh',
              '%s/%s' % (self._module.rbe_cas_input.digest.hash,
                         self._module.rbe_cas_input.digest.size_bytes))
      if self._module.cipd_input:
        return self.then(
          'edit',
          '-rpkg', self._module.cipd_input.package,
          '-rver', self._module.cipd_input.version)
      # TODO(iannucci): Check for/inject buildbucket exe package/version
      return self

    def then(self, *cmd):
      """Invoke led, passing it the current `result` data as input.

      Returns another LedResult object with the output of the command.
      """
      if self._module is None: # pragma: no cover
        raise ValueError(
            'Cannot call LedResult.then on the result of `led launch`')
      res = self._module._run_command(self._result, *cmd)
      return self.__class__(res, self._module)

  def __init__(self, props, **kwargs):
    super().__init__(**kwargs)
    self._run_id = props.led_run_id
    self._shadowed_bucket = props.shadowed_bucket

    if props.HasField('rbe_cas_input'):
      self._rbe_cas_input = props.rbe_cas_input
    else:
      self._rbe_cas_input = None

    if props.HasField('cipd_input'):
      self._cipd_input = props.cipd_input
    else:
      self._cipd_input = None

  def initialize(self):
    if self._test_data.enabled:
      self._get_mocks = {
        key[len('get:'):]: value
        for key, value in self._test_data.items()
        if key.startswith('get:')
      }

      self._mock_edits = self.test_api.standard_mock_functions()
      sorted_edits = sorted([
        (int(key[len('edit:'):]), value)
        for key, value in self._test_data.items()
        if key.startswith('edit:')
      ])
      self._mock_edits.extend(value for _, value in sorted_edits)

  @property
  def led_build(self):
    """Whether the current build is a led job as a real Buildbucket build."""
    return bool(self._shadowed_bucket)

  @property
  def launched_by_led(self):
    """Whether the current build is a led job."""
    return bool(self._run_id) or self.led_build

  @property
  def run_id(self):
    """A unique string identifier for this led job, if it's a raw swarming task.

    If the current build is *not* a led job as raw swarming task, value will be
    an empty string.
    """
    return self._run_id

  @property
  def rbe_cas_input(self):
    """The location of the rbe-cas containing the recipes code being run.

    If set, it will be a `swarming.v1.CASReference` protobuf;
    otherwise, None.
    """
    return self._rbe_cas_input

  @property
  def cipd_input(self):
    """The versioned CIPD package containing the recipes code being run.

    If set, it will be an `InputProperties.CIPDInput` protobuf; otherwise None.
    """
    return self._cipd_input

  @property
  def shadowed_bucket(self):
    """The bucket of the original build/builder the led build replicates from.

    If set, it will be an `InputProperties.ShadowedBucket` protobuf;
    otherwise None.
    """
    return self._shadowed_bucket

  def __call__(self, *cmd):
    """Runs led with the given arguments. Wraps result in a `LedResult`."""
    res = self._run_command(None, *cmd)
    return self.LedResult(res, self)

  def inject_input_recipes(self, led_result):
    """Sets the version of recipes used by led to correspond to the version
    currently being used.

    If neither the `rbe_cas_input` nor the `cipd_input` property is set,
    this is a no-op.

    Args:
      * led_result: The `LedResult` whose job.Definition will be passed into the
        edit command.
    """
    return led_result.with_injected_input_recipes()

  def trigger_builder(
      self,
      project_name,
      bucket_name,
      builder_name,
      properties,
      use_payload=False,
  ):
    """Trigger a builder using led.

    This can be used by recipes instead of buildbucket or scheduler triggers
    in case the running build was triggered by led.

    This is equivalent to:
    led get-builder project/bucket:builder | \
      <inject_input_recipes> | \
      led edit <properties>  | \
      led launch

    Args:
      * project_name - The project that defines the builder.
      * bucket_name - The bucket that configures the builder.
      * builder_name - Name of the builder to trigger.
      * properties - Dict with properties to pass to the triggered build.
      * use_payload - Use edit-payload or edit -rbh to update cas input.
    """
    property_args = []
    for k, v in sorted(properties.items()):
      property_args.append('-p')
      property_args.append('{}={}'.format(k, self.m.json.dumps(v)))

    # Clear out SWARMING_TASK_ID in the environment so that the created tasks
    # do not have a parent task ID. This allows the triggered tasks to outlive
    # the current task instead of being cancelled when the current task
    # completes.
    # TODO(https://crbug.com/1140621) Use command-line option instead of
    # changing environment.
    with self.m.context(env={'SWARMING_TASK_ID': None}):
      builder_id = '{}/{}/{}'.format(project_name, bucket_name, builder_name)
      step_name = 'trigger {}'.format(builder_id)
      with self.m.step.nest(step_name) as builder_presentation:
        led_job = self('get-builder', builder_id)
        led_job = led_job.with_injected_input_recipes(use_payload=use_payload)
        led_job = led_job.then('edit', *property_args)
        result = led_job.then('launch').launch_result
        builder_presentation.links['build'] = result.build_url

  def _get_mock(self, cmd):
    """Returns a StepTestData for the given command."""
    job_def = None

    def _pick_mock(prefix, specific_key):
      # We do multiple lookups potentially, depending on what level of
      # specificity the user has mocked with.
      toks = specific_key.split('/')
      for num_toks in range(len(toks), -1, -1):
        key = '/'.join([prefix] + toks[:num_toks])
        if key in self._get_mocks:
          return self._get_mocks[key]
      return job.Definition()

    if cmd[0] == 'get-builder':
      # "project/bucket:builder" or "luci.project.bucket:builder"
      parts = cmd[-1].split(':', 1)
      if len(parts) == 2:
        bucket = parts[0]
        builder = parts[1]
        if bucket.startswith('luci.'):
          project, bucket = bucket[len('luci.'):].split('.', 1)
        else:
          project, bucket = bucket.split('/', 1)
      else:
        # "project/bucket/builder"
        project, bucket, builder = cmd[-1].split('/')

      mocked = _pick_mock(
          'buildbucket/builder',
          '%s/%s/%s' % (project, bucket, builder))

      if mocked is not None:
        job_def = job.Definition()
        job_def.CopyFrom(mocked)
        job_def.buildbucket.bbagent_args.build.builder.project = project
        job_def.buildbucket.bbagent_args.build.builder.bucket = bucket
        job_def.buildbucket.bbagent_args.build.builder.builder = builder

    elif cmd[0] == 'get-build':
      build_id = str(cmd[-1]).lstrip('b')
      mocked = _pick_mock('buildbucket/build', build_id)
      if mocked is not None:
        job_def = job.Definition()
        job_def.CopyFrom(mocked)
        job_def.buildbucket.bbagent_args.build.id = int(build_id)

    elif cmd[0] == 'get-swarm':
      task_id = cmd[-1]
      mocked = _pick_mock('swarming/task', task_id)
      if mocked is not None:
        job_def = job.Definition()
        job_def.CopyFrom(mocked)
        # To allow easier test mocking, set request_uuid as task_id.
        # It's only used in test to match a job definition with mock_edit_data.
        job_def.swarming.task.request_uuid = task_id

    if job_def is not None:
      return self.test_api.m.proto.output_stream(job_def)

    ret = recipe_test_api.StepTestData()
    ret.retcode = 1
    return ret


  def _run_command(self, previous, *cmd):
    """Runs led with a given command and arguments.

    Args:
      * cmd: The led command to run, e.g. 'get-builder', 'edit', along with any
        arguments.
      * previous: The previous led step's json result, if any. This can be
        used to chain led commands together. See the tests for an example of
        this.

    Ensures that led is checked out on disk before trying to execute the
    command.

    Returns
      * either a job.Definition or a LedLaunchData
    """
    is_launch = cmd[0] == 'launch'

    if is_launch:
      kwargs = {
        'stdout': self.m.json.output(),
      }
      if self._test_data.enabled:
        build_id = previous.buildbucket.bbagent_args.build.id
        if not build_id:
          build_id = 87654321
        kwargs['step_test_data'] = lambda: self.test_api.m.json.output_stream({
            'buildbucket': {
                'host_name': 'buildbucket.appspot.com',
                'build_id': build_id,
            }
        })
    else:
      kwargs = {
        'stdout': self.m.proto.output(job.Definition, 'JSONPB'),
      }
      if self._test_data.enabled:
        if cmd[0].startswith('get-'):
          kwargs['step_test_data'] = lambda: self._get_mock(cmd)
        else:
          # We run this outside of the step_test_data callback to make the stack
          # trace a bit more obvious.
          build = self.test_api._transform_build(
              previous, cmd, self._mock_edits,
              str(self.m.context.cwd or self.m.path.start_dir))
          kwargs['step_test_data'] = (
            lambda: self.test_api.m.proto.output_stream(build))

    if previous is not None:
      kwargs['stdin'] = self.m.proto.input(previous, 'JSONPB')

    result = self.m.step(
        'led %s' % cmd[0], ['led'] + list(cmd), **kwargs)

    if is_launch:
      # If we launched a task, add a link to the swarming task.
      retval = self.LedLaunchData(
          buildbucket_hostname=result.stdout.get('buildbucket',
                                                 {}).get('host_name'),
          build_id=result.stdout.get('buildbucket', {}).get('build_id'),
      )
      result.presentation.links['Build'] = retval.build_url
    else:
      retval = result.stdout

    return retval
