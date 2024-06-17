# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Step is the primary API for running steps (external programs, etc.)"""


import contextlib
from datetime import timedelta
import sys
from typing import Callable, Literal, Sequence

from builtins import int
from past.builtins import basestring

from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from recipe_engine.engine_types import StepPresentation
from recipe_engine.engine_types import ResourceCost as _ResourceCost
from recipe_engine.recipe_test_api import StepTestData
from recipe_engine.util import Placeholder, returns_placeholder
from recipe_engine.recipe_utils import check_type, check_list_type

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class StepApi(recipe_api.RecipeApi):
  step_client = recipe_api.RequireClient('step')

  def __init__(self, step_properties, **kwargs):
    super(StepApi, self).__init__(**kwargs)
    self._prefix_path = step_properties.get('prefix_path', [])

  # Valid step status values.
  EXCEPTION = 'EXCEPTION'
  FAILURE = 'FAILURE'
  INFRA_FAILURE = 'EXCEPTION'  # Buildbucket name for this status
  SUCCESS = 'SUCCESS'
  # Note: although recipes currently have this WARNING status, it's not
  # effecively hooked up to anything in the UI and is treated as SUCCESS.
  #
  # crbug.com/854099
  WARNING = 'WARNING'

  EXT_TO_CODEC = {
    '.pb': 'BINARY',
    '.json': 'JSONPB',
    '.textpb': 'TEXTPB',
  }

  def ResourceCost(self, cpu=500, memory=50, disk=0, net=0):
    """A structure defining the resources that a given step may need.

    The four resources are:

      * cpu (measured in millicores): The amount of cpu the step is expected to
        take. Defaults to 500.
      * memory (measured in MB): The amount of memory the step is expected to
        take. Defaults to 50.
      * disk (as percentage of max disk bandwidth): The amount of "disk
        bandwidth" the step is expected to take. This is a very simplified
        percentage covering IOPS, read/write bandwidth, seek time, etc. At 100,
        the step will run exclusively w.r.t. all other steps having a `disk`
        cost. At 0, the step will run regardless of other steps with disk cost.
      * net (as percentage of max net bandwidth): The amount of "net
        bandwidth" the step is expected to take. This is a very simplified
        percentage covering bandwidth, latency, etc. and is indescriminate of
        the remote hosts, network conditions, etc. At 100, the step will run
        exclusively w.r.t. all other steps having a `net` cost. At 0, the step
        will run regardless of other steps with net cost.

    A step will run when ALL of the resources are simultaneously available. The
    Recipe Engine currently uses a greedy scheduling algorithm for picking the
    next step to run. If multiple steps are waiting for resources, this will
    pick the largest (cpu, memory, disk, net) step which fits the currently
    available resources and run that. The theory is that, assuming:

      * Recipes are finite tasks, which aim to run ALL of their steps, and want
        to do so as quickly as possible. This is not a typical OS scheduling
        scenario where there's some window of time over which the recipe needs
        to be 'fair'. Additionally, recipes run with finite timeouts attached.
      * The duration of a given step is the same regardless of when during the
        build it runs (i.e. running a step now vs later should take roughly the
        same amount of time).

    It's therefore optimal to run steps as quickly as possible, to avoid wasting
    the timeout attached to the build.

    Note that `bool(ResourceCost(...))` is defined to be True if the
    ResourceCost has at least one non-zero cost, and False otherwise.

    Args:
      * cpu (int): Millicores that this step will take to run. See `MAX_CPU`
      helper. A value higher than the maximum number of millicores on the system
      is equivalent to `MAX_CPU`.
      * memory (int): Number of Mebibytes of memory this step will take to run.
      See `MAX_MEMORY` as a helper. A value higher than the maximum amount of
      memory on the system is equivalent to `MAX_MEMORY`.
      * disk (int [0..100]): The disk IO resource this step will take as
      a percentage of the maximum system disk IO.
      * net (int [0..100]): The network IO resource this step will take as
      a percentage of the maximum system network IO.

    Returns:
      a ResourceCost suitable for use with `api.step(...)`'s cost kwarg. Note
      that passing `None` to api.step for the cost kwarg is equivalent to
      `ResourceCost(0, 0, 0, 0)`.
    """
    return _ResourceCost(
        min(cpu, self.MAX_CPU),
        min(memory, self.MAX_MEMORY),
        disk,
        net)

  # The number of millicores in a single CPU core.
  CPU_CORE = 1000

  @property
  def MAX_CPU(self):
    """Returns the maximum number of millicores this system has."""
    return self.m.platform.cpu_count * self.CPU_CORE

  @property
  def MAX_MEMORY(self):
    """Returns the maximum amount of memory on the system in MB."""
    return self.m.platform.total_memory

  @property
  def StepFailure(self):
    """This is the base Exception class for all step failures.

    It can be manually raised from recipe code to cause the build to turn red.

    Usage:
      * `raise api.StepFailure("some reason")`
      * `except api.StepFailure:`
    """
    return recipe_api.StepFailure

  @property
  def StepWarning(self):
    """StepWarning is a subclass of StepFailure, and will translate to a yellow
    build."""
    return recipe_api.StepWarning

  @property
  def InfraFailure(self):
    """InfraFailure is a subclass of StepFailure, and will translate to a purple
    build.

    This exception is raised from steps which are marked as `infra_step`s when
    they fail.
    """
    return recipe_api.InfraFailure

  @property
  def active_result(self):
    """The currently active (open) result from the last step that was run. This
    is a `step_data.StepData` object.

    Allows you to do things like:
    ```python
    try:
      api.step('run test', [..., api.json.output()])
    finally:
      result = api.step.active_result
      if result.json.output:
        new_step_text = result.json.output['step_text']
        api.step.active_result.presentation.step_text = new_step_text
    ```

    This will update the step_text of the test, even if the test fails. Without
    this api, the above code would look like:

    ```python
    try:
      result = api.step('run test', [..., api.json.output()])
    except api.StepFailure as f:
      result = f.result
      raise
    finally:
      if result.json.output:
        new_step_text = result.json.output['step_text']
        api.step.active_result.presentation.step_text = new_step_text
    ```
    """
    return self.step_client.previous_step_result()

  def close_non_nest_step(self):
    """Call this to explicitly terminate the currently open non-nest step.

    After calling this, api.step.active_step will return the current nest step
    context (if any).

    No-op if there's no currently active non-nest step.
    """
    return self.step_client.close_non_parent_step()

  @contextlib.contextmanager
  def nest(self, name, status='worst'):
    """Nest allows you to nest steps hierarchically on the build UI.

    This generates a dummy step with the provided name in the current namespace.
    All other steps run within this `with` statement will be nested inside of
    this dummy step. Nested steps can also nest within each other.

    The presentation for the dummy step can be updated (e.g. to add step_text,
    step_links, etc.) or set the step's status. If you do not set the status,
    it will be calculated from the status' of all the steps run within this one
    according to the `status` algorithm selected.
      1. If there's an active exception when leaving the `with` statement, the
         status will be one of FAILURE, WARNING, EXCEPTION, or CANCELED
         (depending on the type of exception and whether it resulted from the
         child step being canceled).
      2. Otherwise:
         1. If the status algorithm is 'worst', it will assume the status of the
            worst child step. This is useful for when your nest step runs e.g.
            a bunch of test shards. If any shard fails, you want the nest step
            to fail as well.
         2. If the status algorithm is 'last', it will assume the status of the
            last child step. This is useful for when you're using the nest step
            to encapsulate a sequence operation where only the last step's
            status really matters.

    NOTE: Because the nest step allows action on the result of all steps run
    within it, a nest step will wait for ALL recipe code within it (including
    greenlets spawned with api.future.spawn!).

    Example:

        with api.step.nest('run shards'):  # status='worst' is the default.
          with api.defer.context() as defer:
            for shard in shards:
              defer(run_shard, shard)

        # status='last'
        with api.step.nest('do upload', status='last'):
          for attempt in range(num_attempts):
            try:
              do_upload()  # first one fails, but second succeeds.
            except api.step.StepFailure:
              if range >= num_attempts - 1:
                raise
              pass

        # manually adjust status
        with api.step.nest('custom thing') as presentation:
          # stuff!
          presentation.status = 'FAILURE'  # or whatever

    Args:
      * name (str): The name of this step.
      * status ('worst'|'last'): The algorithm to use to pick a
        `presentation.status` if the recipe doesn't set one explicitly.

    Yields a StepPresentation for this dummy step, which you may update as you
    please.
    """
    assert status in ('worst', 'last'), 'Got bad status: %r' % (status,)

    with self.step_client.parent_step(name) as (pres, children_presentations):
      caught_exc = None
      try:
        yield pres
      except:
        caught_exc = sys.exc_info()[1]
        raise
      finally:
        # If they didn't set a presentation.status, calculate one.
        if pres.status is None:
          if caught_exc:
            if not isinstance(caught_exc, recipe_api.StepFailure):
              pres.status = self.EXCEPTION
            elif isinstance(caught_exc, recipe_api.StepWarning):
              pres.status = self.WARNING
            elif caught_exc.was_cancelled:
              # Both `InfraFailures` and non-infra `StepFailures` can have
              # `was_cancelled=True`, hence this check needs to come before the
              # `InfraFailure` check.
              pres.status = 'CANCELED'
            elif isinstance(caught_exc, recipe_api.InfraFailure):
              pres.status = self.EXCEPTION
            else:
              pres.status = self.FAILURE
          elif children_presentations:
            if status == 'worst':
              worst = self.SUCCESS
              for cpres in children_presentations:
                worst = StepPresentation.status_worst(worst, cpres.status)
              pres.status = worst
            else:
              pres.status = children_presentations[-1].status
          else:
            pres.status = self.SUCCESS

  # pylint: disable=too-many-arguments
  def empty(self,
            name,
            status="SUCCESS",
            step_text=None,
            log_text=None,
            log_name='stdout',
            raise_on_failure=True):
    """Runs an "empty" step (one without any command).

    This can be useful to insert a status step/message in the UI, or summarize
    some computation which occurred inside the recipe logic.

    Args:
      name (str) - The name of the step.
      status step.(INFRA_FAILURE|FAILURE|SUCCESS) - The initial status for this
        step.
      step_text (str) - Some text to set for the "step_text" on the presentation
        of this step.
      log_text (str|list(str)) - Some text to set for the log of this step. If
        this is a list(str), will be treated as separate lines of the log.
        Otherwise newlines will be respected.
      log_name (str) - The name of the log to output `log_text` to.
      raise_on_failure (bool) - If set, and `status` is not SUCCESS, raise
        the appropriate exception.

    Returns step_data.StepData.
    """
    ret = self(name, None)
    ret.presentation.status = status
    if step_text:
      ret.presentation.step_text = step_text
    if log_text:
      if hasattr(log_text, 'splitlines'):
        ret.presentation.logs[log_name] = log_text.splitlines()
      else:
        ret.presentation.logs[log_name] = log_text
    if raise_on_failure:
      self.raise_on_failure(ret)
    return ret

  @staticmethod
  def _validate_cmd_list(cmd):
    """Validates cmd is a list and all args in the list have valid types."""
    if not isinstance(cmd, list):
      raise ValueError('cmd must be a list, got %r' % (cmd,))
    for arg in cmd:
      if not isinstance(arg, (int, basestring, Path, Placeholder)):
        raise ValueError('Type %s is not permitted. '
                         'cmd is %r' % (type(arg), cmd))

  @staticmethod
  def _normalize_cost(cost):
    if not isinstance(cost, (type(None), _ResourceCost)):
      raise ValueError('cost must be a None or ResourceCost , got %r' % (cost,))
    return cost or _ResourceCost.zero()

  def _normalize_cwd(self, cwd):
    if cwd and cwd == self.m.path.start_dir:
      cwd = None
    elif cwd is not None:
      cwd = str(cwd)
    return cwd

  def _to_env_affix(self, affix):
    """Returns a `engine_step.EnvAffix` object constructed from input affix (
    i.e. env_prefixes or env_suffixes; see meanings in `context` module) and
    path separator from `path` module.
    """
    return self.step_client.EnvAffix(
        mapping={k: [str(v) for v in vs] for k, vs in affix.items()},
        pathsep=self.m.path.pathsep,
    )

  @returns_placeholder('sub_build')
  def _sub_build_output(self, output_path):
    """Give an output path, returns a build proto output placeholder. The
    encoding format is dictated by the extension of the path.

    If the given output path is None, the output will use binary encoding and
    backed by a temp file.

    ValueError will be raised if:
      * The output path refers to an existing file.
      * The directory of the output path does NOT exist.
      * The extension of output path is not valid (
        i.e. none of [.pb, .json, .textpb])
    """
    if not isinstance(output_path, (type(None), str, Path)): # pragma: no cover
      raise ValueError('expected None, str or Path; got %r' % (output_path,))
    ext = '.pb'
    if output_path is None:
      output_path = self.m.path.mkdtemp() / f'sub_build{ext}'
    else:
      if self.m.path.exists(output_path):
        raise ValueError('expected non-existent output path; '
                         'got path %s' % (output_path,))
      _, ext = self.m.path.splitext(output_path)
      if ext not in self.EXT_TO_CODEC:
        raise ValueError('expected extension of output path to be '
                         'one of %s; got %s' % (tuple(self.EXT_TO_CODEC), ext))
      dir_name = self.m.path.dirname(output_path)
      self.m.path.mock_add_paths(dir_name)
      if not self.m.path.exists(dir_name): # pragma: no cover
        raise ValueError('expected directory of output path exists; '
                         'got dir: %s' % (dir_name,))

    return self.m.proto.output(build_pb2.Build, self.EXT_TO_CODEC[ext],
                              leak_to=output_path,
                              add_json_log=True)

  def _make_initial_build(self, input_build):
    build = build_pb2.Build()
    build.CopyFrom(input_build)
    build.status = common_pb2.STARTED
    if self._test_data.enabled:
      build.create_time.FromSeconds(
          self._test_data.get('initial_build_create_time', 1577836800))
      build.start_time.FromSeconds(
          self._test_data.get('initial_build_start_time', 1577836801))
    else:  # pragma: no cover
      build.create_time.GetCurrentTime()
      build.start_time.GetCurrentTime()
    for f in ('end_time', 'output', 'status_details', 'steps',
              'summary_markdown', 'update_time'):
      build.ClearField(f)
    return build

  def _raise_on_disallowed_statuses(self, result, allowed_statuses,
                                    status_override=None):
    status = status_override or result.presentation.status
    if status in allowed_statuses:
      return result

    # Otherwise we raise an appropriate error based on ret.presentation.status.
    exc = {
        'FAILURE': self.StepFailure,
        'WARNING': self.StepWarning,
        'EXCEPTION': self.InfraFailure,
        'CANCELED': self.InfraFailure,
    }[status]
    # TODO(iannucci): Use '|' instead of '.'
    raise exc('.'.join(result.name_tokens), result)

  def raise_on_failure(self, result, status_override=None):
    """Raise an appropriate exception if a step is not successful.

    Arguments:
      * result - The step result.
      * status_override - An optional status value to override the status
        present on the result of the step. This allows for the exception to
        include information about the result and be based off of the initial
        status even if the step's status has subsequently been changed, which
        aligns with the behavior that would occur if a step was executed with
        raise_on_failure=True and a step's status was changed in a finally
        block.

    Returns:
      If the step's status is SUCCESS, the step result will be returned.

    Raises:
      * StepFailure if the step's status is FAILURE
      * StepWarning if the step's status is WARNING
      * InfraFailure if the step's status is EXCEPTION or CANCELED
    """
    return self._raise_on_disallowed_statuses(
        result, [self.SUCCESS], status_override=status_override)

  def _run_or_raise_step(self, step_config):
    ret = self.step_client.run_step(step_config)
    allowed_statuses = [self.SUCCESS]
    if not step_config.raise_on_failure:
      allowed_statuses += [self.WARNING, self.FAILURE, self.EXCEPTION]
    return self._raise_on_disallowed_statuses(ret, allowed_statuses)

  def sub_build(self,
                name: str,
                cmd: int | str | Placeholder | Path,
                build: build_pb2.Build,
                raise_on_failure: bool = True,
                output_path: str | Path | None = None,
                legacy_global_namespace=False,
                timeout=None,
                step_test_data=None,
                cost=_ResourceCost()):
    """Launch a sub-build by invoking a LUCI executable. All steps in the
    sub-build will appear as child steps of this step (Merge Step).

    See protocol: https://go.chromium.org/luci/luciexe

    Example:

    ```python
    run_exe = api.cipd.ensure_tool(...) # Install LUCI executable `run_exe`

    # Basic Example: launch `run_exe` with empty initial build and
    # default options.
    ret = api.sub_build("launch sub build", [run_exe], build_pb2.Build())
    sub_build = ret.step.sub_build #  access final build proto result

    # Example: launch `run_exe` with input build to recipe and customized
    # output path, cwd and cache directory.
    with api.context(
        # Change the cwd of the launched LUCI executable
        cwd=api.path.start_dir / 'subdir',
        # Change the cache_dir of the launched LUCI executable. Defaults to
        # api.path.cache_dir if unchanged.
        luciexe=sections_pb2.LUCIExe(cache_dir=api.path.cache_dir / 'sub'),
      ):
      # Command executed:
      #   `/path/to/run_exe --output [CLEANUP]/build.json --foo bar baz`
      ret = api.sub_build("launch sub build",
                          [run_exe, '--foo', 'bar', 'baz'],
                          api.buildbucket.build,
                          output_path=api.path.cleanup_dir / 'build.json')
    sub_build = ret.step.sub_build  # access final build proto result
    ```

    Args:
      * name (str): The name of this step.
      * cmd (list[int|string|Placeholder|Path]): Same as the `cmd` parameter in
        `__call__` method except that None is NOT allowed. cmd[0] MUST denote a
        LUCI executable. The `--output` flag and its value should NOT be
        provided in the list. It should be provided via keyword arg
        `output_path` instead.
      * build (build_pb2.Build): The initial build state that the launched
        luciexe will start with. This method will clone the input build, modify
        the clone's fields and pass the clone to luciexe (see 'Invocation'
        section in http://go.chromium.org/luci/luciexe for what modification
        will be done).
      * raise_on_failure: Whether or not the step will raise on failure. If
        True, a StepFailure will be raised if the step's status is FAILURE, an
        InfraFailure will be raised if the step's status is EXCEPTION and a
        StepWarning will be raised if the step's status is WARNING. Regardless
        of the value of this argument, an InfraFailure will be raised if the
        step is canceled.
      * output_path (None|str|Path): The value of the `--output` flag. If
        provided, it should be a path to a non-existent file (its directory
        MUST exist). The extension of the path dictates the encoding format of
        final build proto (See `EXT_TO_CODEC`). If not provided, the output
        will be a temp file with binary encoding.
      * legacy_global_namespace (bool): If set, activates legacy global
        namespace merging. Only meant for legacy ChromeOS builders.
        See crbug.com/1310155.
      * timeout (None|int|float|datetime.timedelta): Same as the `timeout`
        parameter in `__call__` method.
      * step_test_data(Callable[[], recipe_test_api.StepTestData]): Same as the
        `step_test_data` parameter in `__call__` method.
      * cost (None|ResourceCost): Same as the `cost` parameter in `__call__`
        method.

    Returns a `step_data.StepData` for the finished step. The final build proto
    object can be accessed via `ret.step.sub_build`. The build is guaranteed to
    be present (i.e. not None) with a terminal build status.

    Raises `StepFailure` if the sub-build reports FAILURE status.
    Raises `InfraFailure` if the sub-build reports INFRA_FAILURE or CANCELED
    status.
    """

    check_type("name", name, str)
    check_list_type("cmd", cmd, (int, str, Placeholder, Path))
    check_type("build", build, build_pb2.Build)
    check_type("raise_on_failure", raise_on_failure, bool)
    check_type("output_path", output_path, (type(None), str, Path))

    self._validate_cmd_list(cmd)
    cmd = list(cmd)
    # The command may have positional arguments, so place the output flag
    # right after cmd0.
    cmd[1:1] = ['--output', self._sub_build_output(output_path)]

    new_tmp_dir = str(self.m.path.mkdtemp())
    with self.m.context(
        env={
          var: new_tmp_dir for var in (
           'TEMPDIR', 'TMPDIR', 'TEMP', 'TMP', 'MAC_CHROMIUM_TMPDIR')
        },
        env_prefixes={'PATH': self._prefix_path}
      ):
      env = self.m.context.env
      env_prefixes = self.m.context.env_prefixes

    return self._run_or_raise_step(
        self.step_client.StepConfig(
            name=name,
            cmd=cmd,
            cost=self._normalize_cost(cost),
            cwd=self._normalize_cwd(self.m.context.cwd),
            env=env,
            env_prefixes=self._to_env_affix(env_prefixes),
            env_suffixes=self._to_env_affix(self.m.context.env_suffixes),
            timeout=timeout,
            luci_context=self.m.context.luci_context,
            stdin=self.m.proto.input(self._make_initial_build(build), 'BINARY'),
            infra_step=self.m.context.infra_step or False,
            raise_on_failure=raise_on_failure,
            merge_step='legacy' if legacy_global_namespace else True,
            # The return code of LUCI executable should be omitted
            ok_ret=self.step_client.StepConfig.ALL_OK,
            step_test_data=step_test_data,
        ))

  def __call__(self,
               name: str,
               cmd: list[int | str | Placeholder | Path] | None,
               ok_ret: Sequence[int] | Literal['any'] | Literal['all'] = (0,),
               infra_step: bool = False,
               raise_on_failure: bool = True,
               wrapper: Sequence[int | str | Placeholder | Path] = (),
               timeout: int | timedelta | None = None,
               stdout: Placeholder | None = None,
               stderr: Placeholder | None = None,
               stdin: Placeholder | None = None,
               step_test_data: Callable[[], StepTestData] | None = None,
               cost: _ResourceCost = _ResourceCost()):
    """Runs a step (subprocess).

    Args:
      * name (string): The name of this step.
      * cmd (None|List[int|string|Placeholder|Path]): The program arguments to
        run.

        If None or an empty list, then this step just shows up in the UI
        but doesn't run anything (and always has a retcode of 0). See the
        `empty()` method on this module for a more useful version of this mode.

        Otherwise:
        * Numbers and strings are used as-is.
        * Placeholders are 'rendered' to a string (using their render() method).
          Placeholders are e.g. `api.json.input()` or `api.raw_io.output()`.
          Typically rendering these turns into an absolute path to a file on
          disk, which the program is expected to read from/write to.
        * Paths are rendered to an OS-native absolute path.
      * ok_ret (tuple or set of ints, 'any', 'all'): allowed return codes. Any
        unexpected return codes will cause an exception to be thrown. If you
        pass in the value 'any' or 'all', the engine will allow any return code
        to be returned. Defaults to {0}.
      * infra_step: Whether or not this is an infrastructure step.
        Failing infrastructure steps will place the step in an EXCEPTION state
        and if raise_on_failure is True an InfraFailure will be raised.
      * raise_on_failure: Whether or not the step will raise on failure. If
        True, a StepFailure will be raised if the step's status is FAILURE, an
        InfraFailure will be raised if the step's status is EXCEPTION and a
        StepWarning will be raised if the step's status is WARNING. Regardless
        of the value of this argument, an InfraFailure will be raised if the
        step is canceled.
      * wrapper: If supplied, a command to prepend to the executed step as a
        command wrapper.
      * timeout: If supplied, the recipe engine will kill the step after the
        specified number of seconds. Also accepts a datetime.timedelta.
      * stdout: Placeholder to put step stdout into. If used, stdout won't
        appear in annotator's stdout.
      * stderr: Placeholder to put step stderr into. If used, stderr won't
        appear in annotator's stderr.
      * stdin: Placeholder to read step stdin from.
      * step_test_data (func -> recipe_test_api.StepTestData): A factory which
          returns a StepTestData object that will be used as the default test
          data for this step. The recipe author can override/augment this object
          in the GenTests function.
      * cost (None|ResourceCost): The estimated system resource cost of this
        step. See `ResourceCost()`. The recipe_engine will prevent more than the
        machine's maximum resources worth of steps from running at once (i.e.
        steps will wait until there's enough resource available before
        starting). Waiting subprocesses are unblocked in capacity-available
        order. This means it's possible for pending tasks with large
        requirements to 'starve' temporarily while other smaller cost tasks
        run in parallel. Equal-weight tasks will start in FIFO order. Steps
        with a cost of None will NEVER wait (which is the equivalent of
        `ResourceCost()`). Defaults to `ResourceCost(cpu=500, memory=50)`.

    Returns a `step_data.StepData` for the running step.
    """
    cmd = [] if cmd is None else cmd
    self._validate_cmd_list(cmd)

    if cmd and isinstance(
        cmd[0], str) and cmd[0] in ('python', 'vpython'):  # pragma: no cover
      self.m.warning.issue("PYTHON2_DEPRECATED")

    if cmd and wrapper:
      wrapper = list(wrapper)
      self._validate_cmd_list(wrapper)
      if isinstance(
          wrapper[0],
          str) and wrapper[0] in ('python', 'vpython'):  # pragma: no cover
        self.m.warning.issue("PYTHON2_DEPRECATED")
      cmd = wrapper + cmd

    with self.m.context(env_prefixes={'PATH': self._prefix_path}):
      env_prefixes = self.m.context.env_prefixes

    if ok_ret in ('any', 'all'):
      ok_ret = self.step_client.StepConfig.ALL_OK

    return self._run_or_raise_step(
        self.step_client.StepConfig(
            name=name,
            cmd=cmd,
            cost=self._normalize_cost(cost),
            cwd=self._normalize_cwd(self.m.context.cwd),
            env=self.m.context.env,
            env_prefixes=self._to_env_affix(env_prefixes),
            env_suffixes=self._to_env_affix(self.m.context.env_suffixes),
            timeout=timeout,
            luci_context=self.m.context.luci_context,
            infra_step=self.m.context.infra_step or bool(infra_step),
            raise_on_failure=raise_on_failure,
            stdout=stdout,
            stderr=stderr,
            stdin=stdin,
            ok_ret=ok_ret,
            step_test_data=step_test_data,
        ))

  def funcall(self, name, func, *args, **kwargs):
    """Call a function and store the results and exception in a step.

    Sample usage:

    >>> api.step.funcall(None, some_function, 4, json=True)
    """

    name = name or func.__name__

    out = None
    exception = None

    with self.nest(name=name) as presentation:
      presentation.logs["args"] = str(args)
      presentation.logs["kwargs"] = str(kwargs)
      try:
        out = func(*args, **kwargs)
        return out
      except BaseException as e:
        exception = e
        raise e
      finally:
        presentation.logs["out"] = str(out)
        presentation.logs["out_type"] = str(type(out))
        if exception is not None:
          presentation.logs["exception"] = str(exception)
