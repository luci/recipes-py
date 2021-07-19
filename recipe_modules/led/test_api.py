# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.moves.urllib.parse import urlparse
from future.utils import iteritems

import json
import re
import hashlib

import attr

from recipe_engine import recipe_test_api
from recipe_engine.post_process_inputs import Command


from PB.go.chromium.org.luci.led.job import job
from PB.go.chromium.org.luci.buildbucket.proto import common


class LedTestApi(recipe_test_api.RecipeTestApi):
  def __init__(self, *args, **kwargs):
    super(LedTestApi, self).__init__(*args, **kwargs)

    # The ModuleTestData system provided by the recipe engine essentially gives
    # us a `dict` that gets passed to the module's __init__ method during test
    # mode.
    #
    # Every invocation of mock gets a new key (an integer), and the Led recipe
    # api instance will get the merged set of all mock invocations, which it
    # then sorts to recover the invocation order of mock statements.
    #
    # NOTE: Ideally this would reflect the order of _concatenation_, but
    # recipe_engine's limitations around ModuleTestData make this difficult.
    self._mock_edit_key = 0

  def _singleton_mod_data(self, key, val):
    mod_name = self._module.NAME
    ret = recipe_test_api.TestData(None)
    ret.mod_data[mod_name][key] = val
    return ret

  def mock_get_builder(self, job_def, project=None, bucket=None, builder=None):
    """Mocks the initial job.Definition for the given `led get-builder` call.

    This can be used with increasing specificity; If project, bucket and builder
    are all empty/None, this will set the default job.Definition for ALL builds.
    If project is set, but bucket and builder are not, then it sets the default
    for the project, etc.

    The most specific mock always wins. No merging happens; when a get-builder
    step is run, it will look in order for:

      * builder/$project/$bucket/$builder
      * builder/$project/$bucket
      * builder/$project
      * builder

    And stop at the first one it finds.

    It's not valid to set `builder` but leave project or builder None. Likewise
    it's not valid to set `bucket` but leave project None. These will raise
    ValueError in your GenTests function.

    If a get-builder command is un-mocked, the default is an empty
    job.Definition().

    No matter what, the led module will update the project/bucket/builder fields
    of the returned job.Definition during simulation. It's recommended that you
    omit these from `job_def` for clarity in your tests.

    Args:
      * job_def (job.Definition|None) - The initial job value. If `None`, then
        this marks the builder as non-existent, and the `led get-builder` call
        will be simulated to have an exit code of 1.
      * project (str|None) - The LUCI project this builder belongs to.
      * bucket (str|None) - The Buildbucket bucket this builder is in.
      * builder (str|None) - The name of the builder.

    Returns TestData which can be added to a recipe test case.
    """
    assert isinstance(job_def, (job.Definition, type(None)))
    ret = None

    if not project and (bucket or builder): # pragma: no cover
      raise ValueError(
          "`project` is empty, but bucket or builder are set: %r/%r" %
          (bucket, builder))

    if not bucket and builder: # pragma: no cover
      raise ValueError(
          "`bucket` is empty, but builder is set: %r" % (builder,))

    if job_def is not None:
      ret = job.Definition()
      ret.CopyFrom(job_def)

    key = '/'.join(
        token for token in
        ['get:buildbucket/builder', project, bucket, builder]
        if token)

    return self._singleton_mod_data(key, ret)

  def mock_get_build(self, job_def, build_id=None):
    """Mocks the initial job.Definition for the given `led get-build` call.

    Args:
      * job_def (job.Definition|None) - The initial job value. If `None`, then
        this marks the builder as non-existent, and the `led get-builder` call
        will be simulated to have an exit code of 1.
      * build_id (int|None) - The buildbucket build id for the build or None
        to provide the default basis for all get-build calls.

    Returns TestData which can be added to a recipe test case.
    """
    assert isinstance(job_def, (job.Definition, type(None)))
    ret = None
    if job_def is not None:
      ret = job.Definition()
      ret.CopyFrom(job_def)

    key = 'get:buildbucket/build'
    if build_id:
      key += '/%d' % (build_id,)
    return self._singleton_mod_data(key, ret)


  def mock_get_swarm(self, job_def, task_id=None):
    """Mocks the initial job.Definition for the given `led get-swarm` call.

    Args:
      * job_def (job.Definition|None) - The initial job value. If `None`, then
        this marks the builder as non-existent, and the `led get-builder` call
        will be simulated to have an exit code of 1.
      * task_id (str|None) - The swarming task ID for the build or None to
        provide the default basis for all get-swarm calls.

    Returns TestData which can be added to a recipe test case.
    """
    assert isinstance(job_def, (job.Definition, type(None)))
    ret = None
    if job_def is not None:
      ret = job.Definition()
      ret.CopyFrom(job_def)
    key = 'get:swarming/task'
    if task_id:
      key += '/%s' % (task_id,)
    return self._singleton_mod_data(key, ret)

  StopApplyingMocks = object()

  @attr.s
  class _MockEditData(object):
    # Callable[
    #   [job.Definition, List[string], string],
    #   Union[None, StopApplyingMocks]
    # ]
    func = attr.ib()

    # The build_id to restrict this editor to
    build_id = attr.ib(default=None)  # Union[None, str]

    # The command filter to restrict this editor to
    #
    # Tok = Union[re.RegexObject, str]
    cmd_filter = attr.ib(default=None)  # Union[None, Tok, Sequence[Tok]]

  def mock_edit(self, mutate_function, build_id=None, cmd_filter=None):
    """Mock allows you to provide a transformation function for led
    invocations.

    NOTE: If you're adding a mock for led behavior, it may be worth upstreaming
    into the standard_mock_functions() function on this TestApi if it is
    sufficiently general.

    The function `mutate_function` will take as its arguments the current
    led job.Definition proto message, the current led command and the current
    working directory, and is expected to mutate this message however your test
    needs. If the function returns StopApplyingMocks, then no more mock
    functions will be applied to the build message.

    If `build_id` is provided, your mutate_function will only be called if the
    current job.Definition is for:
       * A buildbucket builder with BBAgentArgs.Build.Builder equal to
         `build_id`.
         e.g. `led get-builder project/bucket:builder` ->
               build_id == "buildbucket/builder/$project/$bucket/$builder"
       * A buildbucket job with BBAgentArgs.build.id equal to `build_id`.
         e.g. `led get-build 1234567` ->
               build_id == "buildbucket/build/1234567"
       * A swarming task with the task ID equal to `build_id`.
         e.g. `led get-swarm deadbeef` ->
               build_id == "swarming/deadbeef"

    If `cmd_filter` is provided, your mutate_function will only be called if the
    led command arguments match:
      `cmd_filter in post_process_inputs.Command(led arguments)`
    This means that the following match `['led', 'edit', '-p', 'foo=bar']`:
      * 'edit'
      * re.compile('.*=.*')
      * ['led', 'edit']
      * ['-p', re.compile('foo=.*')]

    NOTE: For a given test case, the mock functions will apply in the order that
    they were CREATED (NOT the order they were concatenated into the test case).
    This is due to recipe engine limitations. For example:

       mock1 = api.led.mock_edit(some_function)
       mock2 = api.led.mock_edit(some_cool_function)
       mock3 = api.led.mock_edit(some_other_function)

       api.test(
         "test_name",
         mock3 + mock1)  # These evaluate in the order (mock1, mock3)

    All functions whose `build_id` and `cmd_filter` match will be executed,
    unless one of them returns StopApplyingMocks.

    By default, the following actions are mocked by default:
      * Editing property values.
      * Editing the recipe input source (i.e. hash, cipd package information).
      * Editing the recipe bundle (digest is based on the current working
        directory of the led command).
      * Editing the CLs attached to the build.
      * Editing the task name attached to the build.
    """
    key = 'edit:%d' % (self._mock_edit_key,)
    self._mock_edit_key += 1
    return self._singleton_mod_data(
        key, LedTestApi._MockEditData(mutate_function, build_id, cmd_filter))

  @staticmethod
  def _derive_build_ids(build):
    """Because users can set any fields on `build`, it may have multiple IDs."""
    ret = set()

    if build.swarming.task.task_id:
      ret.add('swarming/' + build.swarming.task.task_id)

    if build.buildbucket.bbagent_args.build.id:
      ret.add('buildbucket/build/%s'
              % (build.buildbucket.bbagent_args.build.id,))

    if build.buildbucket.bbagent_args.build.builder.bucket:
      ret.add('buildbucket/builder/%s/%s/%s' % (
        build.buildbucket.bbagent_args.build.builder.project,
        build.buildbucket.bbagent_args.build.builder.bucket,
        build.buildbucket.bbagent_args.build.builder.builder))

    return ret

  @classmethod
  def _transform_build(cls, build, cmd, mock_edit_data, cwd):
    ret = job.Definition()
    ret.CopyFrom(build)

    build_ids = cls._derive_build_ids(ret)
    cmd_checker = Command(cmd)

    for edit_data in mock_edit_data:
      if edit_data.build_id and edit_data.build_id not in build_ids:
        continue
      if edit_data.cmd_filter and edit_data.cmd_filter not in cmd_checker:
        continue

      if edit_data.func(ret, cmd, cwd) is cls.StopApplyingMocks:
        break

    return ret

  @staticmethod
  def get_arg_values(cmd, flag):
    """A cheapo way to return all the flag values in `cmd`.

    This will skip any subcommand and then look for the following variants:
      * '-flag' 'value'
      * '--flag' 'value'
      * '-flag=value'
      * '--flag=value'

    If `flag` is a boolean, just ignore the returned 'value'.

    This will not evaluate any arguments past the first token matching '--'.

    If the very last element of cmd matches `flag`, the value will be None.

    This is a "test quality" parser; you can probably succeed in tricking it.

    Returns the list of values found, in the order they were found. If no values
    were found, returns an empty list.
    """
    flag = flag.lstrip('-')   # strip down to just the letters
    flag_prefixes = ('-'+flag, '--'+flag)

    # Trim the command to exclude '--' and anything after it, if present.
    try:
      cmd = cmd[:cmd.index('--')]
    except ValueError:
      pass

    # advance i to start at the index of the first flag
    i = 0
    for tok in cmd:
      if tok.startswith('-'):
        break
      i += 1

    ret = []
    while i < len(cmd):
      tok = cmd[i]
      next_tok = cmd[i+1] if i+1 < len(cmd) else None

      i += 1
      if tok in flag_prefixes:
        ret.append(next_tok)
        i += 1
        continue

      if '=' not in tok:
        continue

      tok, val = tok.split('=', 1)
      if tok in flag_prefixes:
        ret.append(val)

    return ret

  @classmethod
  def standard_mock_functions(cls):
    """This returns several standard mock functions which are ALWAYS active
    for the led module in simulation mode (i.e. they are always applied
    automatically).
    """
    def _apply_properties(build, cmd, _cwd):
      to_set = {}
      vals = [(val, False) for val in cls.get_arg_values(cmd, 'p')]
      vals.extend((val, True) for val in cls.get_arg_values(cmd, 'pa'))
      for arg_value, sloppy_parse in vals:
        if '=' not in arg_value:  # pragma: no cover
          raise ValueError(
              "led edit -p mock: value %r missing '='" % (
                arg_value))

        prop_name, prop_value = arg_value.split('=', 1)
        try:
          to_set[prop_name] = json.loads(prop_value)
        except Exception as ex: # pylint: disable=broad-except
          if sloppy_parse:
            to_set[prop_name] = prop_value
          else: # pragma: no cover
            raise ValueError(
                "led edit -p mock: could not decode %r as JSON value: %s" % (
                  prop_value, ex))

      for k, val in iteritems(to_set):
        build.buildbucket.bbagent_args.build.input.properties[k] = val

    def _edit_input_recipes(build, cmd, _cwd):
      rbhs = cls.get_arg_values(cmd, 'rbh')
      if rbhs:
        rbh = rbhs[-1]
        if '/' in rbh:
          digest, size_bytes = rbh.split('/')
          build.cas_user_payload.digest.hash = digest
          build.cas_user_payload.digest.size_bytes = int(size_bytes)
        else:
          build.user_payload.digest = rbh
        return

      rpkg = cls.get_arg_values(cmd, 'rpkg')
      if rpkg:
        build.buildbucket.bbagent_args.build.exe.cipd_package = rpkg[-1]

      rver = cls.get_arg_values(cmd, 'rver')
      if rver:
        build.buildbucket.bbagent_args.build.exe.cipd_version = rver[-1]

    def _edit_name(build, cmd, _cwd):
      build.buildbucket.name = cls.get_arg_values(cmd, 'name')[-1]

    def _edit_recipe_bundle(build, _cmd, cwd):
      # We use the cwd path as a proxy for the recipes contained in that path.
      build.cas_user_payload.digest.hash = hashlib.sha256(cwd).hexdigest()
      build.cas_user_payload.digest.size_bytes = 1337

    def _edit_cr_cl(build, cmd, _cwd):
      # This mimics the implementation in `led`.
      #
      # Make sure your fake URLs look like:
      #
      #    https://<gerrit_host>/c/<project/path>/+/<change>
      #    https://<gerrit_host>/c/<project/path>/+/<change>/<patchset>
      #
      # And you'll be fine.

      raw = cmd[-1]
      parsed = urlparse(raw)
      toks = filter(bool, parsed.path.split('/'))
      if not toks or toks[0] != 'c':  # pragma: no cover
        raise ValueError("%r: empty/old/bad gerrit URL" % (raw,))
      toks = toks[1:] # remove "c"

      try:
        idx = toks.index('+')
        project_toks, change_patch_toks = toks[:idx], toks[idx+1:]
      except ValueError:  # pragma: no cover
        raise ValueError("%r: could not split on `+`" % (raw,))

      if not project_toks:  # pragma: no cover
        raise ValueError("%r: missing project" % (raw))

      gerrit_change = common.GerritChange(
          host=parsed.netloc, project='/'.join(project_toks))
      gerrit_change.change = int(change_patch_toks[0])
      gerrit_change.patchset = (
        int(change_patch_toks[1]) if len(change_patch_toks) > 1 else 1337)

      bp = build.buildbucket.bbagent_args.build
      if '-remove' in cmd:
        to_remove = []
        for i, change in enumerate(bp.input.gerrit_changes):
          if change == gerrit_change:
            to_remove.append(i)
        for idx in reversed(to_remove):
          del bp.input.gerrit_changes[idx]
      else:
        if '-no-implicit-clear' not in cmd:
          del bp.input.gerrit_changes[:]
        bp.input.gerrit_changes.add().CopyFrom(gerrit_change)

    return [
      cls._MockEditData(_apply_properties, cmd_filter=[
        'edit', Ellipsis, re.compile(r"--?pa?(=.*)?"),
      ]),
      cls._MockEditData(_edit_input_recipes, cmd_filter=[
        'edit', Ellipsis, re.compile(r"--?r(bh|pkg|ver)(=.*)?"),
      ]),
      cls._MockEditData(_edit_name, cmd_filter=[
        'edit', Ellipsis, re.compile(r"--?name(=.*)?"),
      ]),
      cls._MockEditData(_edit_recipe_bundle, cmd_filter=[
        'edit-recipe-bundle',
      ]),
      cls._MockEditData(_edit_cr_cl, cmd_filter=[
        'edit-cr-cl',
      ]),
    ]
