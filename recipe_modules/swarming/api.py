# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
import contextlib
import copy

from collections import namedtuple

from state import TaskState

from recipe_engine import recipe_api


DEFAULT_CIPD_VERSION = 'git_revision:0592590977f837a12f6dad2614a4ae469796b8ec'


# TODO(iannucci): Investigate whether slices can be made invisible to clients
# who only wish to specify a request with a single slice.
class TaskRequest(object):
  """Describes a single Swarming request for a new task.

  A TaskRequest object is immutable and building it up follows the 'constructor'
  pattern. The with_* and add_* methods set the associated value on a copy of
  the object, and return that updated copy.

  A new request has a single empty TaskSlice (see below).

  Example:
  ```
  request = (api.swarming.task_request().
    with_name('my-name').
    with_priority(100).
    with_service_account("my-service-account").
    with_slice(0, (request[0].
        # ...
        # Building up of a TaskSlice, following the same pattern; see below.
      )
    )
  )
  ```

  For more details on what goes into a Swarming task, see the user guide:
  https://chromium.googlesource.com/infra/luci/luci-py/+/master/appengine/swarming/doc/User-Guide.md#task
  """
  def __init__(self, api):
    self._name = ''
    self._priority = 200
    self._service_account = ''
    self._api = api
    self._slices = [self.TaskSlice(api)]

  def _copy(self):
    return copy.copy(self)

  def __getitem__(self, idx):
    """Returns task slice of the given index."""
    return self._slices[idx]

  def __len__(self):
    """Returns the number of task slices comprising the request."""
    return len(self._slices)

  def add_slice(self, slice_obj):
    """Returns the request with the given slice appendedd.

    Args:
      * slice (TaskSlice) - The slice to append.
    """
    ret =  self._copy()
    ret._slices.append(slice_obj)
    return ret

  def with_slice(self, idx, slice_obj):
    """Returns the request with the given slice set at the given index.

    Args:
      * idx (int) - The index at which to set the slice.
      * slice (TaskRequest) - The slice to set.
    """
    assert isinstance(slice_obj, self.TaskSlice)
    assert 0 <= idx < len(self._slices)
    ret =  self._copy()
    ret._slices[idx] = slice_obj
    return ret

  @property
  def name(self):
    """Returns the name of the task."""
    return self._name

  def with_name(self, name):
    """Returns the request with the given name set.

    Args:
      * name (str) - The name of the task.
    """
    assert isinstance(name, str)
    ret =  self._copy()
    ret._name = name
    return ret

  @property
  def priority(self):
    """Returns the priority of the task.

    Priority is a numerical priority between 0 and 255 where a higher number
    corresponds to a lower priority. Tasks are scheduled by swarming in order
    of their priority (e.g. if both a task of priority 1 and a task of
    priority 2 are waiting for resources to free up for execution, the task
    with priority 1 will take precedence).
    """
    return self._priority

  def with_priority(self, priority):
    """Returns the request with the given priority set.

    Args:
      * priority (int) - The priority of the task.
    """
    assert isinstance(priority, int)
    ret =  self._copy()
    ret._priority = priority
    return ret

  @property
  def service_account(self):
    """Returns the service account with which the task will run."""
    return self._service_account

  def with_service_account(self, account):
    """Returns the request with the given service account attached.

    Args:
      * service_account (str) - The service account to attach to the task.
    """
    assert isinstance(account, str)
    ret =  self._copy()
    ret._service_account = account
    return ret

  def to_jsonish(self):
    """Renders the task request as a JSON-serializable dict.

    The format follows the schema given by the NewTaskRequest class found here:
    https://cs.chromium.org/chromium/infra/luci/appengine/swarming/swarming_rpcs.py?q=NewTaskRequest
    """
    return {
      'name': self.name,
      'priority': self.priority,
      'service_account': self.service_account,
      'task_slices': [task_slice.to_jsonish() for task_slice in self._slices],
    }

  class TaskSlice(object):
    """Describes a specification of a Swarming task slice.

    A TaskSlice object is immutable and building it up follows the 'constructor'
    pattern.

    Example:
    ```
    slice = (request[-1].
      with_command(['echo', 'hello']).
      with_dimensions({'pool': 'my.pool', 'os': 'Debian'}).
      with_isolated('606d94add94223636ee516c6bc9918f937823ccc').
      with_expiration_secs(3600).
      with_io_timeout_secs(600)
    )
    """
    def __init__(self, api):
      self._command = []
      self._isolated = ''
      self._dimensions = {}
      self._cipd_ensure_file = api.cipd.EnsureFile()
      self._outputs = []
      self._env_vars = {}
      self._env_prefixes = {}
      self._expiration_secs = 300
      self._io_timeout_secs = 60
      self._hard_timeout_secs = 1200
      self._grace_period_secs = 30
      self._idempotent = False
      self._secret_bytes = ''
      self._api = api

    def _copy(self):
      return copy.copy(self)

    @property
    def command(self):
      """Returns the command (list(str)) the task will run."""
      return copy.copy(self._command)

    def with_command(self, cmd):
      """Returns the slice with the given command set.

      Args:
        cmd (str) - The command the task will run.
      """
      assert isinstance(cmd, list) and all(isinstance(s, str) for s in cmd)
      ret =  self._copy()
      ret._command = cmd
      return ret

    @property
    def isolated(self):
      """Returns the hash of an isolated on the default isolated server.

      The default isolated server is the one set in IsolatedApi.
      """
      return self._isolated

    def with_isolated(self, isolated):
      """Returns the slice with the given isolated hash set.

      Args:
        isolated (str) - The hash of an isolated on the default isolated server.
      """
      assert isinstance(isolated, str)
      ret =  self._copy()
      ret._isolated = isolated
      return ret

    @property
    def dimensions(self):
      """Returns the dimensions (dict[str]str) on which to filter swarming
      bots.
      """
      return self._dimensions.copy()

    def with_dimensions(self, **kwargs):
      """Returns the slice with the given dimensions set.

      A key with a value of None will be interpreted as a directive to unset the
      associated dimension.

      Example:
      ```
      slice = request[-1].with_dimensions(
        SOME_DIM='stuff', OTHER_DIM='other stuff')

      # ...

      if condition:
        slice = slice.with_dimensions(SOME_DIM=None)
      )
      ```
      """
      ret =  self._copy()
      for k, v in kwargs.iteritems():
        assert isinstance(k, str) and (isinstance(v, str) or v == None)
        if v is None:
          ret._dimensions.pop(k, None)
        else:
          ret._dimensions[k] = v
      return ret

    @property
    def cipd_ensure_file(self):
      """Returns the CIPD ensure file (api.cipd.EnsureFile) of packages to
      install.
      """
      return copy.copy(self._cipd_ensure_file)

    def with_cipd_ensure_file(self, ensure_file):
      """Returns the slice with the given CIPD packages set.

      Args:
        ensure_file (api.cipd.EnsureFile) - The CIPD ensure file of the packages
          to install.
      """
      assert isinstance(ensure_file, self._api.cipd.EnsureFile)
      ret =  self._copy()
      ret._cipd_ensure_file = ensure_file
      return ret

    @property
    def outputs(self):
      """Returns the list of files to be isolated on task exit."""
      return copy.copy(self._outputs)

    def with_outputs(self, outputs):
      """Returns the slice with given outputs set.

      Args:
        outputs (list(str)) - Files relative to the swarming task's root
          directory; they are symlinked into $ISOLATED_OUTDIR and isolated upon
          exit of the task.
      """
      assert isinstance(outputs, list)
      assert all(isinstance(output, basestring) for output in outputs)
      ret =  self._copy()
      ret._outputs = outputs
      return ret

    @property
    def env_vars(self):
      """Returns the mapping (dict) of an environment variable to its value."""
      return copy.deepcopy(self._env_vars)

    def with_env_vars(self, **kwargs):
      """Returns the slice with the given environment variables set.

      A key with a value of None will be interpreted as a directive to unset the
      associated environment variable.

      Example:
      ```
      slice = request[-1].with_env_vars(
        SOME_VARNAME='stuff', OTHER_VAR='more stuff', UNSET_ME=None,
      )
      ```
      """
      ret = self._copy()
      for k, v in kwargs.iteritems():
        assert isinstance(k, basestring) and (isinstance(v, basestring) or v is None)
        if v is None:
          ret._env_vars.pop(k, None)
        else:
          ret._env_vars[k] = v
      return ret

    @property
    def env_prefixes(self):
      """Returns a mapping (dict) of an environment variable to the list of
      paths to be prepended."""
      return copy.deepcopy(self._env_prefixes)

    def with_env_prefixes(self, **kwargs):
      """Returns the slice with the given environment prefixes set.

      The given paths are interpeted as relative to the Swarming root directory.

      Successive calls to this method is additive with respect to prefixes: a
      call that sets FOO=[a,...] chained with a call with FOO=[b,...] is
      equivalent to a single call that sets FOO=[a,...,b,...].

      A key with a value of None will be interpreted as a directive to unset the
      associated environment variable.

      Example:
      ```
      slice = request[-1].with_env_prefixes(
        PATH=['path/to/bin/dir', 'path/to/other/bin/dir'], UNSET_ME=None,
      )
      ```
      """
      ret = self._copy()
      for k, v in kwargs.iteritems():
        assert isinstance(k, basestring) and (isinstance(v, list) or v is None), (
          '%r must be a string and %r None or a list of strings' % (k, v))
        if v is None:
          ret._env_prefixes.pop(k, None)
        else:
          assert all(isinstance(prefix, basestring) for prefix in v)
          ret._env_prefixes.setdefault(k, []).extend(v)
      return ret

    @property
    def expiration_secs(self):
      """Returns the seconds before this task expires."""
      return self._expiration_secs

    def with_expiration_secs(self, secs):
      """Returns the slice with the given expiration timeout set.

      Args:
        secs (int) - The seconds before the task expires.
      """
      assert isinstance(secs, int) and secs >= 0
      ret =  self._copy()
      ret._expiration_secs = secs
      return ret

    @property
    def io_timeout_secs(self):
      """Returns the seconds for which the task may be silent (no i/o)."""
      return self._io_timeout_secs

    def with_io_timeout_secs(self, secs):
      """Returns the slice with the given i/o timeout set.

      Args:
        secs (int) - The seconds for which the task the may be silent (no i/o).
      """
      assert isinstance(secs, int) and secs >= 0
      ret =  self._copy()
      ret._io_timeout_secs = secs
      return ret

    @property
    def hard_timeout_secs(self):
      """Returns the seconds before Swarming should kill the task."""
      return self._hard_timeout_secs

    def with_hard_timeout_secs(self, secs):
      """Returns the slice with the given hard timeout set.

      Args:
        secs (int) - The seconds before which Swarming should kill the task.
      """
      assert isinstance(secs, int) and secs >= 0
      ret =  self._copy()
      ret._hard_timeout_secs = secs
      return ret

    @property
    def grace_period_secs(self):
      """Returns the grace period for the slice.

      When a Swarming task is killed, the grace period is the amount of time
      to wait before a SIGKILL is issued to the process, allowing it to
      perform any clean-up operations.
      """
      return self._grace_period_secs

    def with_grace_period_secs(self, secs):
      """Returns the slice with the given grace period set.

      Args:
        secs (int) - The seconds giving the grace period.
      """
      assert isinstance(secs, int) and secs >= 0
      ret =  self._copy()
      ret._grace_period_secs = secs
      return ret

    @property
    def idempotent(self):
      """Returns whether the task is idempotent on a copy of self.

      A task is idempotent if for another task is executed with identical
      properties, we can short-circuit execution and just return the other
      latter's results.
      """
      return self._idempotent

    def with_idempotent(self, idempotent):
      """Returns the slice with the given idempotency set.

      Args:
        idempotent (bool) - Whether the task is idempotent.
      """
      assert isinstance(idempotent, bool)
      ret =  self._copy()
      ret._idempotent = idempotent
      return ret

    @property
    def secret_bytes(self):
      """Returns the data to be passed as secret bytes.

      Secret bytes are base64-encoded data that may be securely passed to the
      task. This returns the raw, unencoded data initially passed.
      """
      return self._secret_bytes

    def with_secret_bytes(self, data):
      """Returns the slice with the given data set as secret bytes.

      Args:
        data (str) - The data to be written to secret bytes.
      """
      assert isinstance(data, str)
      ret =  self._copy()
      ret._secret_bytes = data
      return ret


    def to_jsonish(self):
      """Renders the task request as a JSON-serializable dict.

      The format follows the schema given by the TaskSlice class found here:
      https://cs.chromium.org/chromium/infra/luci/appengine/swarming/swarming_rpcs.py?q=TaskSlice\(
      """
      dims = self.dimensions
      assert len(dims) >= 1 and dims['pool']

      properties = {
        'command': self.command,
        'dimensions': [{'key': k, 'value': v} for k, v in dims.iteritems()],
        'outputs' : self.outputs,
        'env' : [{'key': k , 'value': v} for k, v in self.env_vars.iteritems()],
        'env_prefixes' : [{'key': k , 'value' : v} for k, v in self.env_prefixes.iteritems()],
        'execution_timeout_secs': str(self.hard_timeout_secs),
        'io_timeout_secs': str(self.io_timeout_secs),
        'hard_timeout_secs': str(self.hard_timeout_secs),
        'grace_period_secs': str(self.grace_period_secs),
        'idempotent': self.idempotent,
      }

      if self.isolated:
        properties['inputs_ref'] = {
          'isolated': self.isolated,
          'namespace': 'default-gzip',
          'isolatedserver': self._api.isolated.isolate_server,
        }
      if self.secret_bytes:
        properties['secret_bytes'] = base64.b64encode(self.secret_bytes)
      if len(self.cipd_ensure_file.packages) > 0:
        properties['cipd_input'] = {
          'packages': [
            {
              'package_name': pkg.name,
              'path': path or '',
              'version': pkg.version,
            }
            for path, pkgs in self.cipd_ensure_file.packages.iteritems()
              for pkg in pkgs
          ]
        }

      return {
        'expiration_secs': str(self.expiration_secs),
        'properties': properties,
      }

class TaskRequestMetadata(object):
  """Metadata of a requested task."""
  def __init__(self, swarming_server, task_json):
    self._task_json = task_json
    self._swarming_server = swarming_server

  @property
  def name(self):
    """Returns the name of the associated task."""
    return self._task_json['request']['name']

  @property
  def id(self):
    """Returns the id of the associated task."""
    return self._task_json['task_id']

  @property
  def task_ui_link(self):
    """Returns the URL of the associated task in the Swarming UI."""
    return '%s/task?id=%s' % (self._swarming_server, self.id)

class TaskResult(object):
  """Result of a Swarming task."""

  # A tuple giving the isolated output refs of a task.
  IsolatedOutputs = namedtuple('IsolatedOutputs', ['hash', 'server', 'namespace'])

  def __init__(self, api, id, raw_results, output_dir):
    """
    Args:
      api (recipe_api.RecipeApi): a recipe API.
      id (str): The task's id.
      raw_results (dict): The jsonish summary output from a `collect` call.
      output_dir (Path|None): Where the task's outputs were downloaded to.
    """
    self._api = api
    self._id = id
    self._outputs = {}
    self._isolated_outputs = None
    if 'error' in raw_results:
      self._output = raw_results['error']
      self._name = None
      self._state = None
      self._success = None
      self._duration = None
    else:
      results = raw_results['results']
      self._name = results['name']
      self._state = TaskState[results['state']]

      assert self._state not in [
          TaskState.INVALID, TaskState.PENDING, TaskState.RUNNING,
      ], 'state %s is either invalid or non-final' % self._state.name

      self._success = False
      if self._state == TaskState.COMPLETED:
        # If 0, a default value, exit_code may be omitted by the cloud
        # endpoint's response.
        self._success = results.get('exit_code', 0) == 0

      self._duration = results['duration']

      outputs_ref = results.get('outputs_ref')
      if outputs_ref:
        self._isolated_outputs = self.IsolatedOutputs(
            hash=outputs_ref['isolated'],
            server=outputs_ref['isolatedserver'],
            namespace=outputs_ref['namespace'],
        )

      self._output = raw_results['output']
      if output_dir and raw_results.get('outputs'):
        self._outputs = {
            output: api.path.join(output_dir, output)
                for output in raw_results['outputs']
        }

  @property
  def name(self):
    """The name (str) of the task."""
    return self._name

  @property
  def id(self):
    """The ID (str) of the task."""
    return self._id

  @property
  def state(self):
    """The final state (TaskState|None) of the task.

    Returns None if there was a client-side, RPC-level error in determining the
    result, in which case the task is in an unknown state.
    """
    return self._state

  @property
  def success(self):
    """Returns whether the task completed successfully (bool|None).

    If None, then the task is in an unknown state due to a client-side,
    RPC-level failure.
    """
    return self._success

  @property
  def output(self):
    """The output (str) streamed from the task."""
    return self._output

  @property
  def outputs(self):
    """A map (dict[str]Path) of the files, relative to absolute paths, output
    from the task.

    This dictionary is comprised of the files found in $ISOLATED_OUTDIR upon
    exiting the task, mapping to the paths on disk to where they were
    downloaded.

    There will be no outputs fetched unless api.swarming.collect() was called
    with output_dir set.
    """
    return self._outputs

  @property
  def isolated_outputs(self):
    """Returns the isolated output refs (IsolatedOutputs|None) of the task."""
    return self._isolated_outputs

  def analyze(self):
    """Raises a step failure if the task was unsuccessful."""
    if self.state == None:
      raise self._api.step.InfraFailure('Failed to collect: %s' % self.output)
    elif self.state == TaskState.EXPIRED:
      raise self._api.step.InfraFailure('Timed out waiting for a bot to run on')
    elif self.state == TaskState.TIMED_OUT:
      # Duration is measured in seconds; round down to the nearest one.
      duration = self._duration[:self._duration.find('.')]
      output_lines = self.output.rsplit('\n', 11)
      failure_lines = [
          'Timed out. Last 10 lines of output:',
      ] + output_lines[-10:]
      raise self._api.step.StepTimeout(
          '\n'.join(failure_lines), '%s seconds' % duration)
    elif self.state == TaskState.BOT_DIED:
      raise self._api.step.InfraFailure('The bot running this task died')
    elif self.state == TaskState.CANCELED:
      raise self._api.step.InfraFailure('The task was canceled before it could run')
    elif self.state == TaskState.COMPLETED:
      if not self.success:
        raise self._api.step.InfraFailure('Swarming task failed:\n%s' % self.output)
    elif self.state == TaskState.KILLED:
      raise self._api.step.InfraFailure('The task was killed mid-execution')
    elif self.state == TaskState.NO_RESOURCE:
      raise self._api.step.InfraFailure('Found no bots to run this task')
    else:
      assert False, 'unknown state %s; a case needs to be added above' % (
        self.state.name # pragma: no cover
      )

class SwarmingApi(recipe_api.RecipeApi):
  """API for interacting with swarming.

  The tool's source lives at
  http://go.chromium.org/luci/client/cmd/swarming.

  This module will deploy the client to [CACHE]/swarming_client/; users should
  add this path to the named cache for their builder.
  """
  TaskState = TaskState

  def __init__(self, swarming_properties, *args, **kwargs):
    super(SwarmingApi, self).__init__(*args, **kwargs)
    self._server = swarming_properties.get('server', None)
    self._version = swarming_properties.get('version', DEFAULT_CIPD_VERSION)
    self._client_dir = None
    self._client = None

  def initialize(self):
    if self._test_data.enabled:
      self._server = 'https://example.swarmingserver.appspot.com'
    if self.m.runtime.is_experimental:
      self._version = 'latest'
    self._client_dir = self.m.path['cache'].join('swarming_client')

  def _ensure_swarming(self):
    """Ensures that swarming client is installed."""
    if not self._client:
      with self.m.step.nest('ensure swarming'):
        with self.m.context(infra_steps=True):
          pkgs = self.m.cipd.EnsureFile()
          pkgs.add_package('infra/tools/luci/swarming/${platform}',
                           self._version)
          self.m.cipd.ensure(self._client_dir, pkgs)
          self._client = self._client_dir.join('swarming')

  def _run(self, name, cmd, step_test_data=None):
    """Return an swarming command step.

    Args:
      name: (str): name of the step.
      cmd (list(str|Path)): swarming client subcommand to run.
    """
    self._ensure_swarming()
    return self.m.step(name,
                       [self._client] + list(cmd),
                       step_test_data=step_test_data,
                       infra_step=True)

  @contextlib.contextmanager
  def on_path(self):
    """This context manager ensures the go swarming client is available on
    $PATH.

    Example:

        with api.swarming.on_path():
          # do your steps which require the swarming binary on path
    """
    self._ensure_swarming()
    with self.m.context(env_prefixes={'PATH': [self._client_dir]}):
      yield

  def task_request(self):
    """Creates a new TaskRequest object.

    See documentation for TaskRequest/TaskSlice to see how to build this up into
    a full task.

    Once your TaskRequest is complete, you can pass it to `trigger` in order to
    have it start running on the swarming server.
    """
    return TaskRequest(self.m)

  def trigger(self, requests):
    """Triggers a set of Swarming tasks.

    Args:
      tasks (seq[TaskRequest]): A sequence of task request objects representing
        the tasks we want to trigger.

    Returns:
      A list of TaskRequestMetadata objects.
    """
    assert len(requests) > 0
    assert self._server

    trigger_resp = self._run(
        'trigger %d tasks' % len(requests),
        [
          'spawn-tasks',
          '-server', self._server,
          '-json-input', self.m.json.input({
            'requests': [ req.to_jsonish() for req in requests ]
          }),
          '-json-output', self.m.json.output(),
        ],
        step_test_data=lambda: self.test_api.trigger(
          task_names=tuple(map(lambda req: req.name, requests)),
        )
    ).json.output

    metadata_objs = []
    presented_links = self.m.step.active_result.presentation.links
    for task_json in trigger_resp['tasks']:
      metadata_obj = TaskRequestMetadata(self._server, task_json)
      presented_links['Swarming task UI: %s' % metadata_obj.name] = (
          metadata_obj.task_ui_link)
      metadata_objs.append(metadata_obj)

    return metadata_objs

  def collect(self, name, tasks, output_dir=None, timeout=None):
    """Waits on a set of Swarming tasks.

    Args:
      name (str): The name of the step.
      tasks ((list(str|TaskRequestMetadata)): A list of ids or metadata objects
        corresponding to tasks to wait
      output_dir (Path|None): Where to download the tasks' isolated outputs. If
        set to None, they will not be downloades; else, a given task's outputs
        will be downloaded to output_dir/<task id>/.
      timeout (str|None): The duration for which to wait on the tasks to finish.
        If set to None, there will be no timeout; else, timeout follows the
        format described by https://golang.org/pkg/time/#ParseDuration.

    Returns:
      A list of TaskResult objects.
    """
    assert self._server
    assert isinstance(tasks, list)
    cmd = [
      'collect',
      '-server', self._server,
      '-task-summary-json', self.m.json.output(),
      '-task-output-stdout', 'json',
    ]
    if output_dir:
      cmd.extend(['-output-dir', output_dir])
    if timeout:
      cmd.extend(['-timeout', timeout])

    test_data = []
    for idx, task in enumerate(tasks):
      if isinstance(task, str):
        cmd.append(task)
        test_data.append(self.test_api.task_result(id=task, name='my_task_%d' % idx))
      elif isinstance(task, TaskRequestMetadata):
        cmd.append(task.id)
        test_data.append(self.test_api.task_result(id=task.id, name=task.name))
      else:
        raise ValueError("%s must be a string or TaskRequestMetadata object" %
            task.__repr__()) # pragma: no cover
    step_result = self._run(
        name,
        cmd,
        step_test_data=lambda: self.test_api.collect(test_data),
    )
    parsed_results = [
        TaskResult(self.m,
                   id,
                   task,
                   self.m.path.join(output_dir, id) if output_dir else None)
        for id, task in step_result.json.output.iteritems()
    ]
    # Update presentation on collect to reflect bot results.
    for result in parsed_results:
      if result.output:
        step_result.presentation.logs['Swarming task output: %s' % result.name] = (
          result.output.split('\n')
        )
    return parsed_results
