# -*- coding: utf-8 -*-
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import base64
import collections
import contextlib
import datetime
import copy
import json

from past.types import basestring

from .state import TaskState

from recipe_engine import recipe_api
from recipe_engine import config_types

# Take revision from
# https://ci.chromium.org/p/infra-internal/g/infra-packagers/console
DEFAULT_CIPD_VERSION = 'git_revision:4880e2938a2151dbcb493e5bb9173501606dfe74'

# The mandatory fields to include when calling the API list_bots with fields.
LIST_BOTS_MANDATORY_FIELDS = 'items(bot_id,is_dead,quarantined,maintenance_msg)'


class TaskRequest:
  """Describes a single Swarming request for a new task.

  A TaskRequest object is immutable and building it up follows the 'constructor'
  pattern. The with_* and add_* methods set the associated value on a copy of
  the object, and return that updated copy.

  A new request has a single empty TaskSlice (see below) and it inherits the
  current LUCI realm, if any (see context.realm).

  Example:
  ```
  request = (api.swarming.task_request().
      with_name('my-name').
      with_priority(100).
      with_service_account('my-service-account').
      with_resultdb().
      with_slice(0, (request[0].
          # ...
          # Building up of a TaskSlice, following the same pattern; see below.
          )
      )
  )
  ```

  A more complex example using two task slices:
  ```
  request = (api.swarming.task_request().
      with_name('my-name').
      with_priority(100).
      with_service_account('my-service-account')
  )
  # Initialize a TaskSlice for the fallback, that expires after 58 minutes.
  slice_cold_cache = (request.slice[0].
      with_command(['echo', 'hello']).
      with_dimensions(pool='my.pool', os='Debian').
      with_expiration_secs(60*60-2*60).
      with_io_timeout_secs(600).
      with_named_caches({'image': 'vm_image'})
  )
  # Create a second TaskSlice for the warm cache, that expires after 2 minutes.
  slice_warm_cache = (slice_cold_cache.
      with_dimensions(caches='vm_image').
      with_expiration_secs(2*60)
  )
  # Setup the warm cache first, fallback to the cold cache after. The total task
  # expiration is 60 minutes.
  request = (
      request.
      with_slice(0, slice_warm_cache).
      with_slice(1, slice_cold_cache)
  )
  ```

  For more details on what goes into a Swarming task, see the user guide:
  https://chromium.googlesource.com/infra/luci/luci-py/+/main/appengine/swarming/doc/User-Guide.md#task
  """

  ResultDBCfg = collections.namedtuple('ResultDBCfg', ['enable'])

  def __init__(self, api):
    self._api = api
    self._name = ''
    self._priority = 200
    self._service_account = ''
    self._slices = [self.TaskSlice(api)]
    self._user = None
    self._tags = None
    self._realm = api.context.realm
    self._resultdb = self.ResultDBCfg(enable=False)

  def _copy(self):
    # * api cannot be deepcopied
    # * Naive deepcopy(TaskSlice) won't work, we have to use _copy() to do the
    #   deep copy.
    api = self._api
    self._api = None
    slices = self._slices
    self._slices = []

    ret = copy.deepcopy(self)

    ret._api = api
    ret._slices.extend([s._copy() for s in slices])
    self._api = api
    self._slices = slices
    return ret

  def __getitem__(self, idx):
    """Returns task slice of the given index."""
    return self._slices[idx]

  def __len__(self):
    """Returns the number of task slices comprising the request."""
    return len(self._slices)

  def add_slice(self, slice_obj):
    """Returns the request with the given slice appended.

    Args:
      * slice (TaskSlice) - The slice to append.
    """
    ret = self._copy()
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
    ret = self._copy()
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
    assert isinstance(name, basestring)
    ret = self._copy()
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
    ret = self._copy()
    ret._priority = priority
    return ret

  @property
  def realm(self):
    """Returns the realm of the task."""
    return self._realm

  def with_realm(self, realm):
    """Returns the request with the given realm."""
    assert isinstance(realm, basestring)
    ret = self._copy()
    ret._realm = realm
    return ret

  @property
  def resultdb(self):
    """Returns the ResultDB integration config of the task."""
    return self._resultdb

  def with_resultdb(self):
    """Enables the ResultDB integration in the task.

    Requires the task request to be associated with some LUCI realm.
    """
    ret = self._copy()
    ret._resultdb = self.ResultDBCfg(enable=True)
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
    assert isinstance(account, basestring)
    ret = self._copy()
    ret._service_account = account
    return ret

  @property
  def user(self):
    """Returns the requester of the task.

    User that requested this task, if applicable.
    """
    return self._user

  def with_user(self, user):
    """Returns the slice with the given user.

    Args:
      user (str) - user that requested this task, if applicable.
    """
    assert isinstance(user, basestring)
    ret = self._copy()
    ret._user = user
    return ret

  @property
  def tags(self):
    """Returns the tags associated with the task."""
    return self._tags

  def with_tags(self, tags):
    """Returns the request with the given tags attached.

    Args:
      * tags (Dict[str, List[str]]) - The tags to attach to the task.
    """
    assert isinstance(tags, dict)
    tags_list = []
    for tag, values in tags.items():
      assert isinstance(tag, basestring)
      assert isinstance(values, list)
      for value in values:
        assert isinstance(value, basestring)
        tags_list.append('%s:%s' % (tag, value))
    ret = self._copy()
    ret._tags = sorted(tags_list)
    return ret

  def _from_jsonish(self, d):
    """Constructs a task request from a JSON-serializable dict."""
    # All fields from luci-go set `omitempty`, so the keys might not exist
    # in the JSON when retrieved from luci-go client.
    # See https://chromium.googlesource.com/infra/luci/luci-go/+/refs/heads/main/common/api/swarming/swarming/v1/swarming-gen.go
    # The code below `.get` the "empty value" for the type if omitted.
    tags = collections.defaultdict(list)
    for tag in d.get('tags', ()):
      k, v = tag.split(':', 1)
      tags[k].append(v)
    ret = (self.
        with_name(d.get('name', '')).
        with_priority(int(d.get('priority', 0))).
        with_service_account(d.get('service_account', '')).
        with_tags(tags)) # yapf: disable
    if 'user' in d:
      ret = ret.with_user(d['user'])
    if 'resultdb' in d:
      ret = ret.with_resultdb()
    if 'realm' in d:
      ret = ret.with_realm(d['realm'])
    ret._slices = [
        self.TaskSlice(self._api)._from_jsonish(ts)
        for ts in d.get('task_slices', [])
    ]
    return ret

  def to_jsonish(self):
    """Renders the task request as a JSON-serializable dict.

    The format follows the schema given by the NewTaskRequest class found here:
    https://cs.chromium.org/chromium/infra/luci/appengine/swarming/swarming_rpcs.py?q=NewTaskRequest
    """
    realm = self.realm
    if self.resultdb.enable and not realm:
      # Use realms for tasks with ResultDB even when the parent task is not
      # using them yet. This is needed to allow experimenting with
      # ResultDB-enabled tests before realms are available everywhere.
      #
      # TODO(crbug.com/1122808): Remove this fallback.
      realm = self._api.buildbucket.builder_realm
    ret = {
        'name': self.name,
        'priority': str(self.priority),
        'service_account': self.service_account,
        'task_slices': [task_slice.to_jsonish() for task_slice in self._slices],
    }
    # Omit resultdb, if disabled.
    if self.resultdb.enable:
      ret['resultdb'] = self.resultdb._asdict()
    # Omit them rather than setting to None.
    if self.user:
      ret['user'] = self.user
    if self.tags:
      ret['tags'] = self.tags
    if realm:
      ret['realm'] = realm
    return ret


  class TaskSlice:
    """Describes a specification of a Swarming task slice.

    A TaskSlice object is immutable and building it up follows the 'constructor'
    pattern.

    Example:
    ```
    slice = (request[-1].
      with_command(['echo', 'hello']).
      with_dimensions(pool='my.pool', os='Debian').
      with_expiration_secs(3600).
      with_io_timeout_secs(600)
    )
    """

    def __init__(self, api):
      self._cipd_ensure_file = api.cipd.EnsureFile()
      self._command = []
      self._relative_cwd = ""
      self._dimensions = {}
      self._env_prefixes = {}
      self._env_vars = {}
      self._execution_timeout_secs = 1200
      self._expiration_secs = 300
      self._wait_for_capacity = False
      self._grace_period_secs = 30
      self._idempotent = False
      self._io_timeout_secs = 60
      self._named_caches = {}
      self._outputs = []
      self._secret_bytes = b''
      self._cas_input_root = ''

      # Containment
      self._containment_type = 'NONE'

      self._api = api

    def _copy(self):
      # api cannot be deepcopied
      api = self._api
      self._api = None

      ret = copy.deepcopy(self)

      ret._api = api
      self._api = api
      return ret

    @property
    def command(self):
      """Returns the command (list(str)) the task will run."""
      return self._command[:]

    def with_command(self, cmd):
      """Returns the slice with the given command set.

      Args:
        cmd (str) - The command the task will run.
      """
      assert isinstance(cmd, list)
      assert all(isinstance(s, basestring) for s in cmd)
      ret = self._copy()
      ret._command = cmd
      return ret

    @property
    def relative_cwd(self):
      "The working directory relative to the task root where `command` runs."
      return self._relative_cwd

    def with_relative_cwd(self, relative_cwd):
      """Returns the slice with the given relative_cwd set.

      Args:
        relative_cwd (str) - The path relative to the task root in which to run
          `command`.
      """
      assert isinstance(relative_cwd, basestring)
      ret = self._copy()
      ret._relative_cwd = relative_cwd
      return ret

    @property
    def cas_input_root(self):
      """Returns the digest of an uploaded directory tree on the default cas
      server.

      The default cas server is the one set in CasApi.
      """
      return self._cas_input_root

    def with_cas_input_root(self, digest):
      """Returns the slice with the given cas digest.

      Args:
        digest (str) - The digest of an uploaded directory tree on the default
          cas server.
      """
      assert isinstance(digest, basestring)
      assert digest.count('/') == 1
      ret = self._copy()
      ret._cas_input_root = digest
      return ret

    @property
    def dimensions(self):
      """Returns the dimensions (dict[str]str) on which to filter swarming
      bots.
      """
      return copy.deepcopy(self._dimensions)

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
      ret = self._copy()
      # Make a copy.
      ret._dimensions = self.dimensions
      for k, v in kwargs.items():
        assert isinstance(k, basestring) and (isinstance(v, basestring) or
                                              v is None)
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
      return copy.deepcopy(self._cipd_ensure_file)

    def with_cipd_ensure_file(self, ensure_file):
      """Returns the slice with the given CIPD packages set.

      Args:
        ensure_file (api.cipd.EnsureFile) - The CIPD ensure file of the packages
          to install.
      """
      assert isinstance(ensure_file, self._api.cipd.EnsureFile)
      ret = self._copy()
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
      ret = self._copy()
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
      # Make a copy.
      ret._env_vars = self.env_vars
      for k, v in kwargs.items():
        assert (isinstance(k, basestring) and
                (isinstance(v, basestring) or v is None))
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

      The given paths are interpreted as relative to the Swarming root dir.

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
      # Make a copy.
      ret._env_prefixes = self.env_prefixes
      for k, v in kwargs.items():
        assert (isinstance(k, basestring) and
                (isinstance(v, list) or v is None)), (
                    '%r must be a string and %r None or a list of strings' %
                    (k, v))
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
      ret = self._copy()
      ret._expiration_secs = secs
      return ret

    @property
    def wait_for_capacity(self):
      """Returns whether this task should wait for capacity."""
      return self._wait_for_capacity

    def with_wait_for_capacity(self, b):
      """Returns the slice with wait_for_capacity set to |b|.

      Args:
        b (bool) - Whether or not to wait for capacity.
      """
      assert isinstance(b, bool)
      ret = self._copy()
      ret._wait_for_capacity = b
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
      ret = self._copy()
      ret._io_timeout_secs = secs
      return ret

    @property
    def execution_timeout_secs(self):
      """Returns the seconds before Swarming should kill the task."""
      return self._execution_timeout_secs

    def with_execution_timeout_secs(self, secs):
      """Returns the slice with the given hard timeout set.

      Args:
        secs (int) - The seconds before which Swarming should kill the task.
      """
      assert isinstance(secs, int) and secs >= 0
      ret = self._copy()
      ret._execution_timeout_secs = secs
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
      ret = self._copy()
      ret._grace_period_secs = secs
      return ret

    @property
    def idempotent(self):
      """Returns whether the task is idempotent.

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
      ret = self._copy()
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
        data (bytes) - The data to be written to secret bytes.
      """
      assert isinstance(data, bytes)
      ret = self._copy()
      ret._secret_bytes = data
      return ret

    @property
    def containment_type(self):
      """Returns whether the task process is contained."""
      return self._containment_type

    def with_containment_type(self, containment_type):
      """Returns the slice with the given containment_type set.

      Args:
        containment_type (str) - One of the supported containment types.
      """
      assert containment_type in ('NONE', 'AUTO', 'JOB_OBJECT', 'NOT_SPECIFIED')
      ret = self._copy()
      ret._containment_type = containment_type
      return ret

    @property
    def named_caches(self):
      """Returns the named caches used by this slice."""
      return self._named_caches

    def with_named_caches(self, named_caches):
      """Returns the slice with the given named caches added.

      Args:
        named_caches (dict) - A dict mapping cache name (str)
          to cache path (str).
      """
      assert isinstance(named_caches, dict)
      ret = self._copy()
      ret._named_caches.update(named_caches)
      return ret

    def _from_jsonish(self, d):
      # All fields from luci-go set `omitempty`, so the keys might not exist
      # in the JSON when retrieved from the luci-go client.
      # See https://chromium.googlesource.com/infra/luci/luci-go/+/refs/heads/main/common/api/swarming/swarming/v1/swarming-gen.go
      # The code below `.get` the "empty value" for the type if omitted.
      p = d.get('properties', {})
      containment = p.get('containment', {})

      def kv_list_to_dict(kv_list):
        ret = {}
        for kv in kv_list:
          ret[kv['key']] = kv.get('value', None)
        return ret

      ret = (
          self.with_command(p.get('command', [])).with_relative_cwd(
              p.get('relative_cwd', '')).with_dimensions(
                  **kv_list_to_dict(p.get('dimensions', []))).with_outputs(
                      p.get('outputs', [])).with_env_vars(**kv_list_to_dict(
                          p.get('env', []))).with_env_prefixes(
                              **kv_list_to_dict(p.get('env_prefixes', [])))
          .with_execution_timeout_secs(int(p.get(
              'execution_timeout_secs', 0))).with_grace_period_secs(
                  int(p.get('grace_period_secs', 0))).with_idempotent(
                      p.get('idempotent', False)).with_io_timeout_secs(
                          int(p.get('io_timeout_secs',
                                    0))).with_containment_type(
                                        containment.get('containment_type',
                                                        self.containment_type)))
      if 'cas_input_root' in p:
        digest = p['cas_input_root']['digest']
        ret = ret.with_cas_input_root(digest['hash'] + '/' +
                                      digest.get('size_bytes', '0'))
      if 'secret_bytes' in p:
        ret = ret.with_secret_bytes(base64.b64decode(p['secret_bytes']))
      if 'cipd_input' in p:
        ensure_file = self._api.cipd.EnsureFile()
        for pkg in p['cipd_input']['packages']:
          ensure_file.add_package(
              pkg['package_name'], pkg['version'], subdir=pkg['path'])
        ret = ret.with_cipd_ensure_file(ensure_file)
      if 'caches' in p:
        ret = ret.with_named_caches({c['name']: c['path'] for c in p['caches']})
      if 'wait_for_capacity' in d:
        ret = ret.with_wait_for_capacity(d['wait_for_capacity'])
      return ret.with_expiration_secs(int(d.get('expiration_secs', 0)))

    def to_jsonish(self):
      r"""Renders the task request as a JSON-serializable dict.

      The format follows the schema given by the TaskSlice class found here:
      https://cs.chromium.org/chromium/infra/luci/appengine/swarming/
      swarming_rpcs.py?q=TaskSlice\(
      """
      dims = self.dimensions
      assert len(dims) >= 1 and dims['pool']

      properties = {
          'command': self.command,
          'relative_cwd': self.relative_cwd,
          'dimensions': [{
              'key': k,
              'value': v
          } for k, v in sorted(dims.items())],
          'outputs': self.outputs,
          'env': [{
              'key': k,
              'value': v
          } for k, v in sorted(self.env_vars.items())],
          'env_prefixes': [{
              'key': k,
              'value': v
          } for k, v in sorted(self.env_prefixes.items())],
          'execution_timeout_secs': str(self.execution_timeout_secs),
          'grace_period_secs': str(self.grace_period_secs),
          'idempotent': self.idempotent,
          'io_timeout_secs': str(self.io_timeout_secs),
          'containment': {
              'containment_type':
                  self.containment_type,
          },
      }

      if self.cas_input_root:
        h, b = self.cas_input_root.split('/')
        properties['cas_input_root'] = {
            'cas_instance': self._api.cas.instance,
            'digest': {
                'hash': h,
                'size_bytes': b,
            },
        }

      if self.secret_bytes:
        properties['secret_bytes'] = base64.b64encode(
            self.secret_bytes).decode()
      if self.cipd_ensure_file.packages:
        properties['cipd_input'] = {
            'packages': [{
                'package_name': pkg.name,
                'path': path or '.',
                'version': pkg.version,
            }
                         for path in sorted(self.cipd_ensure_file.packages)
                         for pkg in self.cipd_ensure_file.packages[path]]
        }
      if self._named_caches:
        properties['caches'] = [{
            'name': name,
            'path': path
        } for name, path in sorted(self.named_caches.items())]

      return {
          'expiration_secs': str(self.expiration_secs),
          'wait_for_capacity': self.wait_for_capacity,
          'properties': properties,
      }


class TaskRequestMetadata:
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
    """Returns the ID of the associated task."""
    return self._task_json['task_id']

  @property
  def task_ui_link(self):
    """Returns the URL of the associated task in the Swarming UI."""
    return '%s/task?id=%s' % (self._swarming_server, self.id)

  @property
  def invocation(self):
    """Returns the invocation name of the associated task."""
    return self._task_json.get('task_result', {}).get('resultdb_info',
                                                      {}).get('invocation')


class TaskResult:
  """Result of a Swarming task."""

  class CasOutputs:
    """The cas outputs of a task."""

    def __init__(self, digest, instance):
      self._digest = digest
      self._instance = instance

    @property
    def digest(self):
      """The digest of the CAS outputs (str)."""
      return self._digest

    @property
    def instance(self):
      """The CAS instance where the outputs live (str)."""
      return self._instance

    @property
    def url(self):
      """The URL of the associated CAS UI page."""
      return 'https://cas-viewer.appspot.com/{0}/blobs/{1}/tree'.format(
          self.instance,
          self.digest,
      )

  def __init__(self, api, task_slice, id, raw_results, output_dir=None,
               text_output_file=None):
    """
    Args:
      api (recipe_api.RecipeApi): A recipe API.
      task_slice (TaskSlice): The TaskSlice for the request that led to this
                              task result.
      id (str): The task's ID.
      raw_results (dict): The jsonish summary output from a `collect` call.
      output_dir (Path|None): Where the task's outputs were downloaded to.
      text_output_file (Path|None): Where the task's text output was fetched to.
    """
    self._task_slice = task_slice
    self._id = id
    self._output_dir = output_dir
    self._text_output_file = text_output_file
    self._raw_results = raw_results
    self._outputs = {}
    self._cas_outputs = None
    self._success = None
    self._duration = None
    self._created_ts = None
    self._started_ts = None
    self._completed_ts = None
    self._output = None
    self._name = None
    self._state = None
    self._bot_id = None
    # This happens most often when `collect` times out before the task
    # completed.
    if 'error' in raw_results:
      self._output = raw_results['error']
    else:
      results = raw_results['results']
      self._name = results['name']
      self._state = TaskState[results['state']]
      self._bot_id = results.get('bot_id')
      if not self.finalized:
        return
      if self._state == TaskState.COMPLETED:
        self._success = int(results.get('exit_code', 0)) == 0

      self._duration = results.get('duration', 0)

      def parse_datetime(datetime_str):
        try:
          return datetime.datetime.fromisoformat(datetime_str)
        except (TypeError, ValueError):  # pragma: no cover
          return None

      self._created_ts = parse_datetime(results.get('created_ts'))
      self._started_ts = parse_datetime(results.get('started_ts'))
      self._completed_ts = parse_datetime(results.get('completed_ts'))

      cas_output_root = results.get('cas_output_root')
      if cas_output_root:
        d = cas_output_root['digest']
        self._cas_outputs = self.CasOutputs(
            digest=d['hash'] + '/' + d['size_bytes'],
            instance=cas_output_root['cas_instance'],
        )

      self._output = raw_results.get('output')
      if self._output_dir and raw_results.get('outputs'):
        self._outputs = {
            output: self._output_dir / output
            for output in raw_results['outputs']
        }

  @property
  def finalized(self):
    """True if state is not PENDING or RUNNING."""
    return self._state not in [
        TaskState.PENDING,
        TaskState.RUNNING,
    ]

  @property
  def name(self):
    """The name (str) of the task."""
    return self._name

  @property
  def id(self):
    """The ID (str) of the task."""
    return self._id

  @property
  def raw(self):
    """The jsonish dict that was passed into the constructor as raw_results."""
    return copy.deepcopy(self._raw_results)

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
  def duration_secs(self):
    """Returns the duration of the task, in seconds.

    Returns None if an error occurred.
    """
    return self._duration

  @property
  def created_ts(self):
    """Returns a datetime corresponding to when the task was created.

    Returns None if an error occurred.
    """
    return self._created_ts

  @property
  def started_ts(self):
    """Returns a datetime corresponding to when the task started.

    Returns None if an error occurred.
    """
    return self._started_ts

  @property
  def completed_ts(self):
    """Returns a datetime corresponding to when the task finished.

    Returns None if an error occurred.
    """
    return self._completed_ts

  @property
  def output(self):
    """The output (str) streamed from the task."""
    return self._output

  @property
  def _trimmed_output(self):
    """Returns a limited output for use in exception."""
    if self._output is None:
      return 'None'

    limit = 1000
    out = self._output.strip()
    if len(out) <= limit:
      return out
    out = out[-limit:]
    i = out.find('\n')
    if i == -1:
      out = out[4:]
    elif i:
      out = out[i:]
    return '(…)' + out

  @property
  def output_dir(self):
    """The absolute directory (Path|None) that the task's outputs were
    downloaded to.

    Returns None if the task's outputs were not downloaded.
    """
    return self._output_dir

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
  def cas_outputs(self):
    """Returns the cas output refs (CasOutputs|None) of the task."""
    return self._cas_outputs

  @property
  def text_output_file(self):
    """A Path or None where the task's text output is stored.

    If None, the task's text output is not being stored into a file. See
    'task_output_stdout' in collect(...).
    """
    return self._text_output_file

  @property
  def bot_id(self):
    """The ID (str) of the bot that executed the task."""
    return self._bot_id

  def analyze(self):
    """Raises a step failure if the task was unsuccessful."""
    if self.state is None:
      raise recipe_api.InfraFailure(
          'Failed to collect:\n%s' % self._trimmed_output)
    elif self.state == TaskState.EXPIRED:
      raise recipe_api.InfraFailure('Timed out waiting for a bot to run on')
    elif self.state == TaskState.TIMED_OUT:
      duration = int(self._duration)

      if self._task_slice is None:
        failure_lines = ['Timed out after %s seconds.' % duration]
      else:
        # TODO(crbug.com/916556): Stop guessing.
        if duration >= self._task_slice.execution_timeout_secs:
          failure_lines = [
              'Execution timeout: exceeded %s seconds.' %
              self._task_slice.execution_timeout_secs
          ]
        else:
          failure_lines = [
              'I/O timeout: exceeded %s seconds.' %
              self._task_slice.io_timeout_secs
          ]

      failure_lines.extend(['Output:', self._trimmed_output])

      raise recipe_api.StepFailure('\n'.join(failure_lines))
    elif self.state == TaskState.BOT_DIED:
      raise recipe_api.InfraFailure('The bot running this task died')
    elif self.state == TaskState.CLIENT_ERROR:
      raise recipe_api.InfraFailure(
          'The task encountered an error caused by the client')
    elif self.state == TaskState.CANCELED:
      raise recipe_api.InfraFailure('The task was canceled before it could run')
    elif self.state == TaskState.COMPLETED:
      if not self.success:
        raise recipe_api.InfraFailure(
            'Swarming task failed:\n%s' % self._trimmed_output)
    elif self.state == TaskState.KILLED:
      raise recipe_api.InfraFailure('The task was killed mid-execution')
    elif self.state == TaskState.NO_RESOURCE:
      raise recipe_api.InfraFailure('Found no bots to run this task')
    else:
      assert False, 'unknown state %s; a case needs to be added above' % (
          self.state.name  # pragma: no cover
      )


class BotMetadata:
  """Metadata of a bot."""

  def __init__(self, swarming_server, bot_id, bot_json):
    self._bot_id = bot_id
    self._bot_json = bot_json
    self._swarming_server = swarming_server

    self._dimensions = None
    if 'dimensions' in bot_json:
      self._dimensions = {d['key']: d['value'] for d in bot_json['dimensions']}

    self._state = None
    if 'state' in bot_json:
      self._state = json.loads(bot_json['state'])

  @property
  def bot_id(self):
    """The id of the bot (str)."""
    return self._bot_id

  @property
  def bot_ui_link(self):
    """Returns the URL of the associated bot in the Swarming UI."""
    return '%s/bot?id=%s' % (self._swarming_server, self.bot_id)

  @property
  def is_dead(self):
    """True if the bot is dead (bool)."""
    return self._bot_json.get('is_dead', False)

  @property
  def quarantined(self):
    """True if the bot is quarantined (bool)."""
    return self._bot_json.get('quarantined', False)

  @property
  def maintenance_msg(self):
    """The maintenance message for the bot (None|str)."""
    return self._bot_json.get('maintenance_msg')

  @property
  def in_maintenance(self):
    """True if the bot is in maintenance mode (bool)."""
    return bool(self.maintenance_msg)

  @property
  def dimensions(self):
    """The dimensions of the bot (None|Dict[str, List[str]])."""
    return self._dimensions

  @property
  def state(self):
    """The state of the bot (None|Dict[str, Object]).

    The state contains detailed properties of the bot, e.g. disk spaces, env,
    ssd, etc. For bots with OS like Android and ChromeOS, it may have extra
    properties like "devices" which includes device specific data.
    """
    return self._state


class SwarmingApi(recipe_api.RecipeApi):
  """API for interacting with swarming.

  The tool's source lives at
  http://go.chromium.org/luci/client/cmd/swarming.

  This module will deploy the client to [CACHE]/swarming_client/; users should
  add this path to the named cache for their builder.
  """
  TaskState = TaskState
  TaskResult = TaskResult

  def __init__(self, env_properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._server = env_properties.SWARMING_SERVER
    self._env_properties = env_properties
    # Stores TaskRequests by tuple of (task_id, server)
    self._task_requests = {}

  @property
  def bot_id(self):
    """Swarming bot ID executing this task."""
    return self._env_properties.SWARMING_BOT_ID

  @property
  def task_id(self):
    """This task's Swarming ID."""
    return self._env_properties.SWARMING_TASK_ID

  @property
  def current_server(self):
    """Swarming server executing this task."""
    return self._env_properties.SWARMING_SERVER

  def initialize(self):
    if self._test_data.enabled:
      if not self._env_properties.SWARMING_SERVER:
        self._server = 'https://example.swarmingserver.appspot.com'
        self._env_properties.SWARMING_SERVER = self._server
      # Recipes always run on top of swarming task now.
      self._env_properties.SWARMING_TASK_ID = (
          self._env_properties.SWARMING_TASK_ID or 'fake-task-id')
      self._env_properties.SWARMING_BOT_ID = (
              self._env_properties.SWARMING_BOT_ID or 'fake-bot-id')

  @property
  def _version(self):
    if self._test_data.enabled:
      return 'swarming_module_pin'
    return DEFAULT_CIPD_VERSION  # pragma: no cover

  @property
  def _client(self):
    return self.m.cipd.ensure_tool('infra/tools/luci/swarming/${platform}',
                                   self._version)

  def ensure_client(self):
    self._client

  def _run(self, name, cmd, step_test_data=None, **kwargs):
    """Return an swarming command step.

    Args:
      name: (str): name of the step.
      cmd (list(str|Path)): swarming client subcommand to run.
    """
    return self.m.step(
        name, [self._client] + list(cmd),
        step_test_data=step_test_data,
        infra_step=True,
        **kwargs)

  @contextlib.contextmanager
  def on_path(self):
    """This context manager ensures the go swarming client is available on
    $PATH.

    Example:

        with api.swarming.on_path():
          # do your steps which require the swarming binary on path
    """
    client_dir = self.m.path.dirname(self._client)
    with self.m.context(env_prefixes={'PATH': [client_dir]}):
      yield

  def task_request(self):
    """Creates a new TaskRequest object.

    See documentation for TaskRequest/TaskSlice to see how to build this up
    into a full task.

    Once your TaskRequest is complete, you can pass it to `trigger` in order to
    have it start running on the swarming server.
    """
    return TaskRequest(self.m)

  def task_request_from_jsonish(self, json_d):
    """Creates a new TaskRequest object from a JSON-serializable dict.

    The input argument should match the schema as the output of
    TaskRequest.to_jsonish().
    """
    return TaskRequest(self.m)._from_jsonish(json_d)

  def trigger(self, step_name, requests, verbose=False, server=None):
    """Triggers a set of Swarming tasks.

    Args:
      step_name (str): The name of the step.
      requests (seq[TaskRequest]): A sequence of task request objects
        representing the tasks we want to trigger.
      verbose (bool): Whether to use verbose logs.
      server (string): Address of the server to trigger the task on, e.g.
        https://chromium-swarm.appspot.com. If not set, the server the current
        task is running on is used.

    Returns:
      A list of TaskRequestMetadata objects.
    """
    assert requests
    assert self._server

    if not server:
      server = self._server

    requests_dict = {'requests': [req.to_jsonish() for req in requests]}
    cmd = [
        'spawn-tasks',
        '-server',
        server,
        '-json-input',
        self.m.json.input(requests_dict),
        '-json-output',
        self.m.json.output(),
    ]
    if verbose:
      cmd.append('-verbose')

    step = self._run(
        step_name,
        cmd,
        step_test_data=lambda: self.test_api.trigger(
            task_names=tuple(req.name for req in requests),
            resultdb=tuple(req.resultdb.enable for req in requests)))
    trigger_resp = step.json.output

    metadata_objs = []
    for task_json in trigger_resp['tasks']:
      metadata_objs.append(TaskRequestMetadata(server, task_json))

    for idx, req in enumerate(requests):
      self._task_requests[(metadata_objs[idx].id, server)] = req

    metadata_objs.sort(key=lambda obj: obj.name)
    for obj in metadata_objs:
      step.presentation.links['task UI: %s' % obj.name] = obj.task_ui_link
    step.presentation.logs['json.input'] = self.m.json.dumps(
        requests_dict, indent=2)

    return metadata_objs

  def collect(self, name, tasks, output_dir=None, task_output_stdout='json',
              timeout=None, eager=False, verbose=False):
    """Waits on a set of Swarming tasks.

    Args:
      name (str): The name of the step.
      tasks (Iterable(str|TaskRequestMetadata)): A list of task IDs or metadata
        objects corresponding to tasks to wait for.
      output_dir (Path|None): Where to download the tasks' isolated outputs. If
        set to None, they will not be downloaded; else, a given task's outputs
        will be downloaded to output_dir/<task id>/.
      task_output_stdout (str|Path|Iterable(str|Path)): Where to output each
        task's text output. If given an iterable, will output it into multiple
        locations. Supported values are 'none', 'json', 'console' or a Path. At
        most one output Path is allowed. Accepts 'all' as a legacy alias for
        ['json', 'console'].
      timeout (str|None): The duration for which to wait on the tasks to finish.
        If set to None, there will be no timeout; else, timeout follows the
        format described by https://golang.org/pkg/time/#ParseDuration.
      eager (bool): Whether to return as soon as the first task finishes,
        instead of waiting for all tasks to finish.
      verbose (bool): Whether to use verbose logs.

    Returns:
      A list of TaskResult objects.
    """
    assert self._server
    assert isinstance(tasks, (list, tuple))

    cmd = [
        'collect',
        '-server',
        self._server,
        '-task-summary-json',
        self.m.json.output(),
    ]

    if isinstance(task_output_stdout, (basestring, config_types.Path)):
      task_output_stdout = [task_output_stdout]
    text_output_dir = None
    for out in task_output_stdout:
      if isinstance(out, config_types.Path):
        if text_output_dir:
          raise ValueError('Cannot specify more than one task text output dir')
        text_output_dir = out
        out = 'dir:%s' % out
      else:
        assert out in ('none', 'json', 'console', 'all'), out
      cmd.extend(['-task-output-stdout', out])

    if output_dir:
      cmd.extend(['-output-dir', output_dir])
    if timeout:
      cmd.extend(['-timeout', timeout])
    if verbose:
      cmd.append('-verbose')
    if eager:
      cmd.append('-eager')

    test_data = []
    for idx, task in enumerate(tasks):
      if isinstance(task, basestring):
        cmd.append(task)
        test_data.append(
            self.test_api.task_result(id=task, name='my_task_%d' % idx))
      elif isinstance(task, TaskRequestMetadata):
        cmd.append(task.id)
        test_data.append(self.test_api.task_result(id=task.id, name=task.name))
      else:
        raise ValueError("%s must be a string or TaskRequestMetadata object" %
                         task.__repr__())  # pragma: no cover

    # Assume we only need to reserve 10% of a CPU core (rather than 50%) for
    # collect.
    cpu_tenth = int(self.m.step.CPU_CORE / 10)
    cost = self.m.step.ResourceCost(cpu=cpu_tenth)

    step = self._run(
        name,
        cmd,
        step_test_data=lambda: self.test_api.collect(test_data),
        cost=cost,
    )

    parsed_results = []
    for task_id, task in step.json.output.items():
      task_request = self._task_requests.get((task_id, self._server), [None])[0]
      parsed_results.append(
          TaskResult(self.m, task_request, task_id, task,
                     output_dir / task_id if output_dir else None,
                     text_output_dir / f'{task_id}.txt'
                        if text_output_dir else None))

    parsed_results.sort(key=lambda result: result.name or '')

    # Update presentation on collect to reflect bot results.
    for result in parsed_results:
      if result.output is not None:
        log_name = 'task stdout+stderr: %s' % result.name
        step.presentation.logs[log_name] = result.output.splitlines()
      if result.cas_outputs:
        link_name = 'task cas outputs: %s' % result.name
        step.presentation.links[link_name] = result.cas_outputs.url

    return parsed_results

  def show_request(self, name, task):
    """Retrieve the TaskRequest for a Swarming task.

    Args:
      name (str): The name of the step.
      task (str|TaskRequestMetadata): Task ID or metadata objects of the
        swarming task to be retrieved.

    Returns:
      TaskRequest objects.
    """
    assert self._server
    assert isinstance(task, (basestring, TaskRequestMetadata))
    cmd = [
        'request-show',
        '-server',
        self._server,
    ]

    if isinstance(task, basestring):
      cmd.append(task)
    elif isinstance(task, TaskRequestMetadata):
      cmd.append(task.id)
    else:
      raise ValueError("%s must be a string or TaskRequestMetadata object" %
                       task.__repr__())  # pragma: no cover

    step = self._run(
        name,
        cmd,
        step_test_data=lambda: self.test_api.show_request(),
        stdout=self.m.json.output(),
    )
    json_result = step.stdout

    return self.task_request_from_jsonish(json_result)

  def list_bots(self, step_name, dimensions=None, fields=None):
    """List bots matching the given options.

    Args:
      step_name (str): The name of the step.
      dimensions (None|Dict[str, str]): Select bots that match the given
        dimensions.
      fields (None|List[str]): Fields to include in the response. If not
        specified, all fields will be included.

    Returns:
      A list of BotMetadata objects.
    """
    assert self._server
    cmd = [
        'bots',
        '-server',
        self._server,
        '-json',
        self.m.json.output(),
    ]
    if dimensions:
      for key, value in dimensions.items():
        cmd.extend(['-dimension', '%s=%s' % (key, value)])
    if fields:
      cmd.extend(['-field', LIST_BOTS_MANDATORY_FIELDS])
      for field in fields:
        cmd.extend(['-field', field])
    step = self._run(
        step_name,
        cmd,
        step_test_data=lambda: self.test_api.list_bots(dimensions))
    resp = step.json.output

    metadata_objs = []
    for bot_json in resp:
      assert 'bot_id' in bot_json, '"bot_id" not found in the response.'
      metadata_objs.append(
          BotMetadata(self._server, bot_json['bot_id'], bot_json))

    metadata_objs.sort(key=lambda obj: obj.bot_id)

    if dimensions:
      step.presentation.logs['Dimensions to lookup'] = self.m.json.dumps(
          dimensions, indent=2)
    if fields:
      step.presentation.logs['Fields to include'] = ', '.join(fields)

    return metadata_objs

  def list_tasks(self, step_name, start=None, tags=None):
    """List tasks matching the given options.

    Args:
      step_name (str): The name of the step.
      start (None|float): Number of seconds since epoch.
      tags (None|List[str]): Select tasks that contain the given
        tags.

    Returns:
      Json listing the resulting tasks.
    """
    assert self._server
    cmd = [
        'tasks',
        '-server',
        self._server,
        '-json',
        self.m.json.output(),
    ]

    if tags:
      for tag in tags:
        cmd.extend(['-tag', tag])
    if start:
      cmd.extend(['-start', str(start)])
    step = self._run(
        step_name,
        cmd,
        step_test_data=lambda: self.m.json.test_api.output([{
            'task_id': 12341234,
            'tags': tags,
            'completed_ts': '2025-04-21T18:47:23.324102Z',
            'started_ts': '2025-04-21T18:45:44.426350Z',
        }]),
    )
    return step.json.output
