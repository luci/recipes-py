# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import bdb
import copy
import datetime
import inspect
import io
import json
import logging
import os
import re
import sys
import traceback

from contextlib import contextmanager

from future.utils import raise_

import attr
import gevent
import gevent.local

from google.protobuf import json_format as jsonpb
from pympler import summary, tracker

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.recipe_engine import engine_properties as engine_properties_pb2
from PB.recipe_engine import result as result_pb2

from .. import recipe_api
from .. import util
from ..step_data import StepData, ExecutionResult
from ..engine_types import StepPresentation, thaw
from ..engine_types import PerGreenletState, PerGreentletStateRegistry
from ..third_party import luci_context

from . import debugger

from .engine_env import merge_envs
from .exceptions import RecipeUsageError, CrashEngine
from .global_shutdown import GLOBAL_SHUTDOWN
from .resource_semaphore import ResourceWaiter
from .step_runner import Step


LOG = logging.getLogger(__name__)
MAX_SUMMARY_MARKDOWN_SIZE = 4000


@attr.s(frozen=True, slots=True, repr=False)
class _ActiveStep(object):
  """The object type that we keep in RecipeEngine._step_stack."""
  step_data = attr.ib()    # type: StepData
  step_stream = attr.ib()  # type: StepStream
  is_parent = attr.ib()    # type: bool

  children_presentations = attr.ib(factory=list)  # type: List[StepPresentation]
  greenlets = attr.ib(factory=list)               # type: List[gevent.Greenlet]

  def close(self):
    """If step_data is set, finalizes its StepPresentation with
    self.step_stream, then closes self.step_stream.
    """
    gevent.wait(self.greenlets)
    if self.step_data:
      self.step_data.presentation.finalize(self.step_stream)
      self.step_stream.close()

class _MemoryProfiler(object):
  """The memory profiler used in recipe engine that is backed by Pympler.

  Note: This class is currently not thread safe. The snapshot operation is not
  atomic. The profiler will be called before each step execution. Therefore, it
  is okay for now as steps are executed serially. However, once we start to
  execute steps in parallel, the implementation needs to be re-evaluated to
  ensure the atomicity of snapshot operation
  """
  def __init__(self, initial_snapshot_name='Bootstrap'):
    self._current_snapshot_name = initial_snapshot_name
    self._diff_snapshot = False
    self._tracker = tracker.SummaryTracker()

  def snapshot(self, snapshot_name):
    """Snapshot the memory.

    Returns [generator of str] - formatted memory snapshot or diff surrounded
    by dividing line. When this method is called for the first time, the full
    snapshot will be returned. After that,  it will only return the diff with
    the previous snapshot.
    """
    memsum = self._tracker.create_summary()
    last_snapshot_name = self._current_snapshot_name
    self._current_snapshot_name = snapshot_name
    if self._diff_snapshot:
      yield ((
        '-------- Diff between current snapshot (%s) and last snapshot (%s) '
        'Starts --------') % (snapshot_name, last_snapshot_name))
      diff = self._tracker.diff(summary1=memsum)
      # TODO(yiwzhang): switch to yield from after moving to python 3
      for diff_line in summary.format_(diff):
        yield diff_line
      yield ((
        '-------- Diff between current snapshot (%s) and last snapshot (%s) '
        'Ends --------') % (snapshot_name, last_snapshot_name))
    else:
      # create_summary() won't make the return value latest summary in the
      # underlying tracker. Manually moving it forward
      self._tracker.s0 = memsum
      # Only dump the full snapshot when this method is called for the first
      # time. From then onwards, dump diff only
      self._diff_snapshot = True
      yield '-------- Memory Snapshot (%s) Start --------' % snapshot_name
      # TODO(yiwzhang): switch to yield from after moving to python 3
      for snapshot_line in summary.format_(memsum):
        yield snapshot_line
      yield '-------- Memory Snapshot (%s) Ends --------' % snapshot_name


def _get_reasons(exception: Exception) -> list[str]:
  if isinstance(exception, ExceptionGroup):
    reasons = []
    for exc in exception.exceptions:
      reasons.extend(_get_reasons(exc))
    return reasons

  elif isinstance(exception, recipe_api.StepFailure):
    return [exception.reason]

  else:
    return [str(exception)]


class RecipeEngine(object):
  """
  Knows how to execute steps emitted by a recipe, holds global state such as
  step history and build properties. Each recipe module API has a reference to
  this object.

  Recipe modules that are aware of the engine:
    * properties - uses engine.properties.
    * step - uses engine.create_step(...), and previous_step_result.
  """

  def __init__(self, recipe_deps, step_runner, stream_engine, warning_recorder,
               properties, environ, start_dir, initial_luci_context,
               num_logical_cores, memory_mb):
    """See run_steps() for parameter meanings."""
    self._recipe_deps = recipe_deps
    self._step_runner = step_runner
    self._stream_engine = stream_engine  # type: StreamEngine
    self._properties = properties
    self._engine_properties = _get_engine_properties(properties)
    self._environ = environ.copy()
    self._start_dir = start_dir
    self._clients = {client.IDENT: client for client in (
        recipe_api.ConcurrencyClient(
            stream_engine.supports_concurrency,
            self.spawn_greenlet),
        recipe_api.LUCIContextClient(initial_luci_context),
        recipe_api.PathsClient(start_dir),
        recipe_api.PropertiesClient(properties),
        recipe_api.StepClient(self),
        recipe_api.WarningClient(warning_recorder, recipe_deps),
    )}

    self._resource = ResourceWaiter(num_logical_cores * 1000, memory_mb)
    self._memory_profiler = _MemoryProfiler() if (
        self._engine_properties.memory_profiler.enable_snapshot) else None

    # A greenlet-local store which holds a stack of _ActiveStep objects, holding
    # the most recently executed step at each nest level (objects deeper in the
    # stack have lower nest levels). When we pop from this stack, we close the
    # corresponding step stream.
    #
    # NOTE: Due to the way that steps are run in the recipe engine, only the tip
    # of this stack may be a 'real' step; i.e. anything other than the tip of
    # the stack is a parent nesting step.
    class StepStack(PerGreenletState):
      steps = [_ActiveStep(None, None, True)] # "root" parent

      def _get_setter_on_spawn(self):
        tip_step = self.steps[-1]
        def _inner():
          self.steps = [tip_step]
        return _inner

    self._step_stack_storage = StepStack()

    # Map of namespace_tuple -> {step_name: int} to deduplicate `step_name`s
    # within a namespace.
    self._step_names = {}

  @property
  def _step_stack(self):
    return self._step_stack_storage.steps

  @property
  def properties(self):
    """Used by recipe_deps._instantiate_api and recipe_deps.Recipe._run_steps"""
    return self._properties

  @property
  def environ(self):
    """Used by recipe_deps._instantiate_api and recipe_deps.Recipe._run_steps"""
    return self._environ

  def resolve_requirement(self, req: recipe_api.UnresolvedRequirement):
    """Resolves a requirement or raises ValueError if it cannot be resolved.

    Args:
      * req (UnresolvedRequirement): The requirement to resolve.

    Returns the resolved requirement.
    Raises ValueError if the requirement cannot be satisfied.
    """
    assert isinstance(req, recipe_api.UnresolvedRequirement)
    if req._typ == 'client':
      return self._clients.get(req._name)
    raise ValueError('Unknown requirement type [%s]' % (req._typ,))

  def initialize_path_client_HACK(self, root_api):
    """This is a hack; the "PathsClient" currently works to provide a reverse
    string->Path lookup by walking down the recipe's `api` object and calling
    the various 'root' path methods (like .resource(), etc.).

    However, we would like to eventually simplify the 'paths' system, whose
    whole complexity exists to facilitate 'pure-data' config.py processing,
    which is also going to be deprecated in favor of protos and removal of the
    config subsystem.

    Args:
      * root_api (RecipeScriptApi): The root `api` object which would be passed
        to the recipe's RunSteps function.
    """
    self._clients['paths']._initialize_with_recipe_api(root_api)

  def record_import_warning(self, warning, importer):
    """Records an import warning."""
    self._clients['warning'].record_import_warning(warning, importer)

  def close_non_parent_step(self):
    """Closes the tip of the _step_stack if it's not a parent nesting step."""
    try:
      tip_step = self._step_stack[-1]
      if tip_step.is_parent:
        return

      self._step_stack.pop().close()
    except:
      _log_crash(self._stream_engine, "close_non_parent_step()")
      raise CrashEngine("Closing non-parent step failed.")

  @property
  def active_step(self):
    """Returns the current _ActiveStep.step_data.

    May be None if the _ActiveStep is the root _ActiveStep.
    """
    return self._step_stack[-1].step_data

  def spawn_greenlet(self, func, args, kwargs, greenlet_name):
    """Returns a gevent.Greenlet which has been initialized with the correct
    greenlet-local-storage state.

    Args:
      * greenlet_name (str|None) - If non-None, assign this to the greenlet's
        name.
    """
    self.close_non_parent_step()

    to_run = [pgs._get_setter_on_spawn() for pgs in PerGreentletStateRegistry]

    current_step = self._step_stack[-1]
    def _runner():
      for fn in to_run:
        fn()
      try:
        return func(*args, **kwargs)
      finally:
        self.close_non_parent_step()
    ret = gevent.spawn(_runner)
    if greenlet_name is not None:
      ret.name = greenlet_name
    # need stack frames here, rather than greenlet 'lightweight' stack
    ret.spawning_frames = [frame_tup[0] for frame_tup in inspect.stack(2)]
    current_step.greenlets.append(ret)
    return ret

  def _record_step_name(self, name):
    """Records a step name in the current namespace.

    Args:

      * name (str) - The name of the step we want to run in the current context.

    Side effect:
      * calls close_non_parent_step.
      * Updates global tracking state for this step name.

    Returns Tuple[str] of the step name_tokens that should ACTUALLY run.
    """
    self.close_non_parent_step()

    try:
      namespace = ()
      if self.active_step:
        namespace = self.active_step.name_tokens
      cur_state = self._step_names.setdefault(namespace, {})
      cur_count = cur_state.setdefault(name, 0)
      dedup_name = name
      if cur_count:
        dedup_name = name + ' (%d)' % (cur_count + 1)
      cur_state[name] += 1
      return namespace + (dedup_name,)
    except:
      _log_crash(self._stream_engine, "_record_step_name(%r)" % (name,))
      raise CrashEngine("Getting name tokens for %r failed." % (name,))

  def _write_memory_snapshot(self, log_stream, snapshot_name):
    """Snapshot the memory and write the result to the supplied log stream if
    the memory snapshot is enabled.

    Args:
      * log_stream (Stream) - stream that the diff will write to. An None
      stream will make this method no-op
      * snapshot_name (str) - Name of the snapshot. The name will be preserved
      along with the snapshot

    TODO(crbug.com/1057844): After luciexe rolls out, instead of writing the
    log to arbitrary log stream, it should constantly write to memory_profile
    log stream created in setup_build step to consolidate all memory snapshots
    in one UI page.
    """
    if self._memory_profiler and log_stream:
      for line in self._memory_profiler.snapshot(snapshot_name):
        log_stream.write_line(line)

  @contextmanager
  def parent_step(self, name):
    """Opens a parent step with the given name in the current namespace.

    Args:
      * name (str) - The name of the parent step to open.

    Yields a tuple of (StepPresentation, List[StepData]):
      * The StepPresentation for this parent step.
      * The List of children StepData of this parent step.
    """
    name_tokens = self._record_step_name(name)

    try:
      step_data = StepData(name_tokens, ExecutionResult(retcode=0))
      # TODO(iannucci): Use '|' instead of '.'
      presentation = StepPresentation('.'.join(name_tokens))
      self._step_stack[-1].children_presentations.append(presentation)
      step_data.presentation = presentation
      step_data.finalize()

      active_step = _ActiveStep(
          step_data,
          self._stream_engine.new_step_stream(name_tokens, False),
          True)
      active_step.step_stream.mark_running()
      self._step_stack.append(active_step)
    except:
      _log_crash(self._stream_engine, "parent_step(%r)" % (name_tokens))
      raise CrashEngine("Prepping parent step %r failed." % (name_tokens))

    try:
      yield presentation, active_step.children_presentations
    finally:
      try:
        self.close_non_parent_step()
        self._step_stack.pop().close()
      except:
        _log_crash(
            self._stream_engine, "parent_step.close(%r)" % (name_tokens,))
        raise CrashEngine("Closing parent step %r failed." % (name_tokens,))

  def run_step(self, step_config):
    """Runs a step.

    Args:
      step_config (StepConfig): The step configuration to run.

    Returns:
      A StepData object containing the result of the finished step.
    """
    # TODO(iannucci): When subannotations are handled with annotee, move
    # `allow_subannotations` into recipe_module/step.

    name_tokens = self._record_step_name(step_config.name)

    # TODO(iannucci): Start with had_exception=True and overwrite when we know
    # we DIDN'T have an exception.
    ret = StepData(name_tokens, ExecutionResult())

    try:
      self._step_runner.register_step_config(name_tokens, step_config)
    except:
      # Test data functions are not allowed to raise exceptions. Instead of
      # letting user code catch these, we crash the test immediately.
      _log_crash(self._stream_engine, "register_step_config(%r)" % (ret.name,))
      raise CrashEngine("Registering step_config failed for %r." % (
        ret.name
      ))

    step_stream = self._stream_engine.new_step_stream(name_tokens,
      step_config.allow_subannotations, merge_step=step_config.merge_step)
    caught = None
    try:
      # initialize presentation to show an exception.
      ret.presentation = StepPresentation(step_config.name)
      ret.presentation.status = 'EXCEPTION'

      # Add `presentation` to the parents of the active step.
      self._step_stack[-1].children_presentations.append(ret.presentation)

      self._step_stack.append(_ActiveStep(ret, step_stream, False))

      # NOTE: It's important to not open debug_log until:
      #   1) We know we're going to have to quit due to GLOBAL_SHUTDOWN; OR
      #   2) We know we have the resources to run this step.
      #
      # Otherwise if we open it here, the recipe can run out of file descriptors
      # in the event that it has many, many blocked steps.
      debug_log = None
      try:  # _run_step should never raise an exception, except for GreenletExit
        if GLOBAL_SHUTDOWN.ready():
          debug_log = step_stream.new_log_stream('$debug')
          debug_log.write_line('GLOBAL_SHUTDOWN already active, skipping step.')
          step_stream.mark_running()   # to set start time, etc.
          raise gevent.GreenletExit()

        def _if_blocking():
          step_stream.set_summary_markdown(
              'Waiting for resources: `%s`' % (step_config.cost,))
        with self._resource.wait_for(step_config.cost, _if_blocking):
          debug_log = step_stream.new_log_stream('$debug')
          step_stream.mark_running()
          try:
            self._write_memory_snapshot(
              debug_log, 'Step: %s' % '.'.join(name_tokens))
            caught = _run_step(
                debug_log, ret, step_stream, self._step_runner, step_config,
                self._environ, self._start_dir)
          finally:
            # NOTE: See the accompanying note in stream.py.
            step_stream.reset_subannotation_state()
      except gevent.GreenletExit:
        ret.exc_result = attr.evolve(ret.exc_result, was_cancelled=True)
      finally:
        if debug_log:
          debug_log.close()

      ret.finalize()

      if step_config.merge_step:
        _update_merge_step_presentation(ret.presentation,
                                        ret.step.sub_build,
                                        step_stream.user_namespace,
                                        step_config.infra_step)

      # If there's a buffered exception, we raise it now.
      if caught:
        raise_(caught[0], caught[1], caught[2])

      return ret

    finally:
      # per sys.exc_info this is recommended in python 2.x to avoid creating
      # garbage cycles.
      del caught

  def _setup_build_step(self, recipe, emit_initial_properties):
    with self._stream_engine.new_step_stream(('setup_build',), False) as step:
      step.mark_running()
      if emit_initial_properties:
        for key in sorted(self.properties):
          step.set_build_property(
              key, json.dumps(self.properties[key], sort_keys=True))

      run_recipe_help_lines = [
          'To repro this locally, run the following line from the root of a %r'
            ' checkout:' % (self._recipe_deps.main_repo.name),
          '',
          '%s run --properties-file - %s <<EOF' % (
              os.path.join(
                  '.', self._recipe_deps.main_repo.simple_cfg.recipes_path,
                  'recipes.py'),
              recipe),
      ]
      run_recipe_help_lines.extend(
          json.dumps(self.properties, indent=2).splitlines())
      run_recipe_help_lines += [
          'EOF',
          '',
          'To run on Windows, you can put the JSON in a file and redirect the',
          'contents of the file into run_recipe.py, with the < operator.',
      ]

      with step.new_log_stream('run_recipe') as log:
        for line in run_recipe_help_lines:
          log.write_line(line)

      with step.new_log_stream('memory_profile') as memory_log:
        self._write_memory_snapshot(memory_log, 'Step: setup_build')

      step.write_line('Running recipe with %s' % (self.properties,))
      py_ver = '%d.%d.%d' % (
          sys.version_info.major,
          sys.version_info.minor,
          sys.version_info.micro,
      )
      step.add_step_text('running recipe: "%s" with Python %s' % (
          recipe, py_ver))

  @classmethod
  def run_steps(cls, recipe_deps, properties, stream_engine, step_runner,
                warning_recorder, environ, cwd, initial_luci_context,
                num_logical_cores, memory_mb,
                emit_initial_properties=False, test_data=None,
                skip_setup_build=False):
    """Runs a recipe (given by the 'recipe' property). Used by all
    implementations including the simulator.

    Args:
      * recipe_deps (RecipeDeps) - The loaded recipe repo dependencies.
      * properties: a dictionary of properties to pass to the recipe.  The
        'recipe' property defines which recipe to actually run.
      * stream_engine: the StreamEngine to use to create individual step
        streams.
      * step_runner: The StepRunner to use to 'actually run' the steps.
      * warning_recorder: The WarningRecorder to use to record the warnings
        issued while running a recipe.
      * environ: The mapping object representing the environment in which
        recipe runs. Generally obtained via `os.environ`.
      * cwd (str): The current working directory to run the recipe.
      * initial_luci_context (Dict[str, Dict]): The content of LUCI_CONTEXT to
        pass to the recipe.
      * num_logical_cores (int): The number of logical CPU cores to assume the
        machine has.
      * memory_mb (int): The amount of memory to assume the machine has, in MiB.
      * emit_initial_properties (bool): If True, write the initial recipe engine
          properties in the "setup_build" step.

    Returns a 2-tuple of:
      * result_pb2.RawResult
      * The tuple containing exception info if there is an uncaught exception
          triggered by recipe code or None

    Does NOT raise exceptions.
    """
    result = result_pb2.RawResult()
    uncaught_exception = None

    assert 'recipe' in properties
    recipe = properties['recipe']

    try:
      # This does all loading and importing of the recipe script.
      recipe_obj = recipe_deps.main_repo.recipes[recipe]
      # Make sure `global_symbols` (which is a cached execfile of the recipe
      # python file) executes here so that we can correctly catch any
      # RecipeUsageError exceptions which exec'ing it may cause.
      # TODO(iannucci): Make this @cached_property more explicit (e.g.
      # 'load_global_symbols' and 'cached_global_symbols' or something).
      _ = recipe_obj.global_symbols

      engine = cls(
          recipe_deps, step_runner, stream_engine, warning_recorder,
          properties, environ, cwd, initial_luci_context, num_logical_cores,
          memory_mb)
      api = recipe_obj.mk_api(engine, test_data)
      engine.initialize_path_client_HACK(api)
    except (RecipeUsageError, ImportError, AssertionError) as ex:
      _log_crash(stream_engine, 'loading recipe')
      # TODO(iannucci): differentiate infra failure and user failure; will
      # result in expectation changes, but that should be safe in its own CL.
      result.status = common_pb2.INFRA_FAILURE
      result.summary_markdown = 'Uncaught exception: ' + util.format_ex(ex)
      return result, uncaught_exception

    # TODO(iannucci): Don't skip this during tests (but maybe filter it out from
    # expectations).
    if not skip_setup_build:
      try:
        engine._setup_build_step(recipe, emit_initial_properties)
      except Exception as ex:
        _log_crash(stream_engine, 'setup_build')
        result.status = common_pb2.INFRA_FAILURE
        result.summary_markdown = 'Uncaught Exception: ' + util.format_ex(ex)
        return result, uncaught_exception

    try:
      try:
        try:
          raw_result = recipe_obj.run_steps(api, engine)
          if raw_result is None:
            result.status = common_pb2.SUCCESS
          # Notify user that they used the wrong recipe return type.
          elif not isinstance(raw_result, result_pb2.RawResult):
            result.status = common_pb2.FAILURE
            result.summary_markdown = ('"%r" is not a valid return type for '
            'recipes. Did you mean to use "RawResult"?' % (type(raw_result), ))
          else:
            result.CopyFrom(raw_result)
        finally:
          # TODO(iannucci): give this more symmetry with parent_step
          engine.close_non_parent_step()
          engine._step_stack[-1].close()   # pylint: disable=protected-access

      except* recipe_api.StepFailure as ex:
        if debugger.should_set_implicit_breakpoints():

          # =========================================================
          # DEBUG: RunSteps just exited with a StepFailure exception.
          # =========================================================
          breakpoint()  # pylint: disable=forgotten-debug-statement

        reasons = _get_reasons(ex)
        is_infra_failure = False
        was_cancelled = recipe_api.was_cancelled(ex)
        for sub_ex in ex.exceptions:
          if isinstance(sub_ex, recipe_api.InfraFailure):
            is_infra_failure = True

        if was_cancelled and GLOBAL_SHUTDOWN.ready():
          # We presume if we caught a cancelation exception and GLOBAL_SHUTDOWN
          # is on that the original exception was due to GLOBAL_SHUTDOWN... this
          # isn't 100% guaranteed, but for now it's close enough.
          result.status = common_pb2.CANCELED
        elif is_infra_failure:
          result.status = common_pb2.INFRA_FAILURE
        else:
          result.status = common_pb2.FAILURE

        # The encoded summary markdown length has a hard limit. We include as
        # many of the triggering exceptions as possible without exceeding the
        # limit.
        parts = []

        max_size = MAX_SUMMARY_MARKDOWN_SIZE - 25

        for i, reason in enumerate(reasons):
          # Always include the first exception.
          if i == 0 or len('\n'.join([*parts, reason])) < max_size:
            parts.append(reason)

          else:
            num_hidden = len(reasons) - len(parts)
            parts.append(
                f'\n({num_hidden}/{len(reasons)} errors truncated)'
            )

        result.summary_markdown = '\n'.join(parts)

    except bdb.BdbQuit:  # let debugger quit flow through
      raise

    # All other exceptions are reported to the user and are fatal.
    except Exception as ex:  # pylint: disable=broad-except
      if debugger.should_set_implicit_breakpoints():

        # =============================================================
        # DEBUG: RunSteps just exited with a non-StepFailure exception.
        # =============================================================
        breakpoint()  # pylint: disable=forgotten-debug-statement

      _log_crash(stream_engine, 'Uncaught exception')
      result.status = common_pb2.INFRA_FAILURE
      result.summary_markdown = 'Uncaught Exception: ' + util.format_ex(ex)
      uncaught_exception = sys.exc_info()

    except CrashEngine as ex:
      _log_crash(stream_engine, 'Engine Crash')
      result.status = common_pb2.INFRA_FAILURE
      result.summary_markdown = util.format_ex(ex)

    return result, uncaught_exception


def _set_initial_status(presentation, step_config, exc_result):
  """Calculates and returns a StepPresentation.status value from a StepConfig
  and an ExecutionResult.
  """
  # TODO(iannucci): make StepPresentation.status enumey instead of stringy.
  presentation.had_timeout = exc_result.had_timeout
  presentation.was_cancelled = exc_result.was_cancelled

  # TODO(iannucci): there should really be a TIMEOUT status, I think:
  #   CANCELED: externally imposed interrupt
  #   TIMEOUT: self-imposed timeout
  if exc_result.was_cancelled:
    presentation.status = 'CANCELED'
    return

  if exc_result.had_exception:
    presentation.status = 'EXCEPTION'
    return

  if (step_config.ok_ret is step_config.ALL_OK or
      exc_result.retcode in step_config.ok_ret):
    presentation.status = 'SUCCESS'
    return

  presentation.status = 'EXCEPTION' if step_config.infra_step else 'FAILURE'


def _update_merge_step_presentation(presentation, sub_build,
                                    user_namespace, infra_step):
  """Update the step presentation for merge step based on the result sub build.

  Overrides the presentation status with the status of the sub-build. If the
  status of the sub-build is CANCELED, the presentation status will be set to
  INFRA_FAILURE because there's no CANCELED status support in StepPresentation.
  TODO(crbug.com/1096713): Support setting CANCELED Status through
  StepPresentation after getting rid of annotator mode.

  The summary_markdown of the sub-build will be appended to step text and all
  logs in the output of the sub-build will be merged into to the step logs.

  If any of the following conditions is matched, the status will be explicitly
  set to INFRA_FAILURE and the summary_markdown and output logs won't be merged

    * The luciexe that the current merge step invokes does NOT write its final
      build proto to the provided output location.
    * The final build proto reports a non-terminal status.
  """
  def append_step_text(text):
    if presentation.step_text:
      presentation.step_text += '\n'
    presentation.step_text += text
  if presentation.status != 'SUCCESS':
    # Something went wrong already before we check the sub build proto.
    # Return immediately so that error is not masked.
    return
  elif sub_build is None:
    presentation.status = 'EXCEPTION'
    append_step_text(
      "Merge Step Error: Can't find the final build output for luciexe.")
  elif not (sub_build.status & common_pb2.ENDED_MASK):
    presentation.status = 'EXCEPTION'
    append_step_text(
      'Merge Step Error: expected terminal build status of sub build; '
      'got status: %s.' % common_pb2.Status.Name(sub_build.status))
  else:
    presentation.status = {
      common_pb2.SUCCESS: 'SUCCESS',
      common_pb2.FAILURE: 'EXCEPTION' if infra_step else 'FAILURE',
      common_pb2.CANCELED: 'EXCEPTION',
      common_pb2.INFRA_FAILURE: 'EXCEPTION',
    }[sub_build.status]
    if sub_build.summary_markdown:
      append_step_text(sub_build.summary_markdown)
    if sub_build.output.logs:
      for log in sub_build.output.logs:
        merged_log = common_pb2.Log()
        merged_log.MergeFrom(log)
        if user_namespace:
          merged_log.url = '/'.join((user_namespace, log.url))
        presentation.logs[log.name] = merged_log

def _get_engine_properties(properties):
  """Retrieve and resurrect JSON serialized engine properties from all
  properties passed to recipe.

  The serialized value is associated with key '$recipe_engine'.

  Args:

    * properties (dict): All input properties for passed to recipe

  Returns a engine_properties_pb2.EngineProperties object
  """
  return jsonpb.ParseDict(
    properties.get('$recipe_engine', {}),
    engine_properties_pb2.EngineProperties(),
    ignore_unknown_fields=True)

def _prepopulate_placeholders(step_config, step_data):
  """Pre-fills the StepData with None for every placeholder available in
  `step_config`. This is so that users don't have to worry about various
  placeholders not existing on StepData."""
  for itm in step_config.cmd:
    if isinstance(itm, util.OutputPlaceholder):
      step_data.assign_placeholder(itm, None)


def _resolve_output_placeholders(
  debug, name_tokens, step_config, step_data, step_runner):
  """Takes the original (unmodified by _render_placeholders) step_config and
  invokes the '.result()' method on every placeholder. This will update
  'step_data' with the results.

  `step_runner` is used for `placeholder` which should return test data
  input for the InputPlaceholder.cleanup and OutputPlaceholder.result methods.
  """
  for itm in step_config.cmd:
    if isinstance(itm, util.Placeholder):
      test_data = step_runner.placeholder(name_tokens, itm)
      if isinstance(itm, util.InputPlaceholder):
        debug.write_line('  cleaning %r' % (itm,))
        itm.cleanup(test_data.enabled)
      else:
        debug.write_line('  finding result of %r' % (itm,))
        step_data.assign_placeholder(itm, itm.result(
            step_data.presentation, test_data))

  if step_config.stdin:
    debug.write_line('  cleaning stdin: %r' % (step_config.stdin,))
    step_config.stdin.cleanup(
        step_runner.handle_placeholder(name_tokens, 'stdin').enabled)

  for handle in ('stdout', 'stderr'):
    placeholder = getattr(step_config, handle)
    if placeholder:
      debug.write_line('  finding result of %s: %r' % (handle, placeholder))
      test_data = step_runner.handle_placeholder(name_tokens, handle)
      setattr(step_data, handle, placeholder.result(
          step_data.presentation, test_data))


def _render_config(debug, name_tokens, step_config, step_runner, step_stream,
                   environ, start_dir):
  """Returns
    * a step_runner.Step which is ready for consumption by
      StepRunner.run. None if render fails.
    * reason for render failure. None if render succeeds.

  `step_runner` is used for `placeholder` and `handle_placeholder`
  which should return test data input for the Placeholder.render method
  (or an empty test data object).
  """
  cmd = []
  debug.write_line('rendering placeholders')
  for itm in step_config.cmd:
    if isinstance(itm, util.Placeholder):
      debug.write_line('  %r' % (itm,))
      cmd.extend(itm.render(step_runner.placeholder(name_tokens, itm)))
    else:
      cmd.append(itm)

  handles = {}
  debug.write_line('rendering std handles')
  std_handle_reqs = {}
  for handle in ('stdout', 'stderr', 'stdin'):
    placeholder = getattr(step_config, handle)
    if placeholder:
      debug.write_line('  %s: %r' % (handle, placeholder))
      placeholder.render(step_runner.handle_placeholder(name_tokens, handle))
      # TODO(iannucci): maybe verify read/write permissions for backing_file
      # here?
      handles[handle] = placeholder.backing_file
    elif handle == 'stdin':
      handles[handle] = None
    else:
      std_handle_reqs[handle] = True
  if std_handle_reqs:
    handles.update(step_stream.open_std_handles(**std_handle_reqs))

  debug.write_line('merging envs')
  pathsep = step_config.env_suffixes.pathsep
  # TODO(iannucci): remove second return value from merge_envs, it's not needed
  # any more.
  env, _ = merge_envs(environ,
      step_config.env,
      step_config.env_prefixes.mapping,
      step_config.env_suffixes.mapping,
      pathsep)
  env.update(step_stream.env_vars)

  step_luci_context = step_config.luci_context
  if step_luci_context or step_config.timeout:
    debug.write_line('writing LUCI_CONTEXT file')

    if step_config.timeout:
      ideal_soft_deadline = step_runner.now() + step_config.timeout

      step_luci_context = dict(step_luci_context) if step_luci_context else {}
      d = step_luci_context.get('deadline', None)
      if d:
        d = copy.deepcopy(d)
        if d.soft_deadline:  # finite
          d.soft_deadline = min(ideal_soft_deadline, d.soft_deadline)
        else: # infinite
          d.soft_deadline = ideal_soft_deadline
      else:
        d = sections_pb2.Deadline(
            soft_deadline=ideal_soft_deadline, grace_period=30)
      step_luci_context['deadline'] = d

    section_values = {
      key: jsonpb.MessageToDict(pb_val) if pb_val is not None else None
      for key, pb_val in step_luci_context.items()
    }

    if step_config.timeout:
      # the json serialization is nicer to print here
      debug.write_line('  adjusted deadline: %r' % (
        section_values['deadline'],))

    lctx_file = step_runner.write_luci_context(section_values)
    debug.write_line('  done: %r' % (lctx_file,))
    env[luci_context.ENV_KEY] = lctx_file

  debug.write_line('checking cwd: %r' % (step_config.cwd,))
  cwd = step_config.cwd or start_dir
  if not step_runner.isabs(name_tokens, cwd):
    debug.write_line('  not absolute: %r' % (cwd,))
    return None, 'cwd %r is not absolute' % (cwd,)
  if not step_runner.isdir(name_tokens, cwd):
    debug.write_line('  not a directory: %r' % (cwd,))
    return None, 'cwd %r is not a directory' % (cwd,)
  if not step_runner.access(name_tokens, cwd, os.R_OK):
    debug.write_line('  no read perms: %r' % (cwd,))
    return None, 'no read perms on cwd %r' % (cwd,)

  path = env.get('PATH', '').split(pathsep)
  debug.write_line('resolving cmd0 %r' % (cmd[0],))
  debug.write_line('  in PATH: %s' % (path,))
  debug.write_line('  with cwd: %s' % (cwd,))
  cmd0 = step_runner.resolve_cmd0(name_tokens, debug, cmd[0], cwd, path)
  if cmd0 is None:
    debug.write_line('failed to resolve cmd0')
    return Step(
        cmd=tuple(cmd),
        cwd=cwd,
        env=env,
        luci_context=step_luci_context,
        **handles), 'cmd0 %r not found' % (cmd[0],)
  debug.write_line('resolved cmd0: %r' % (cmd0,))

  return Step(
      cmd=(cmd0,) + tuple(cmd[1:]),
      cwd=cwd,
      env=env,
      luci_context=step_luci_context,
      **handles), None


def _run_step(debug_log, step_data, step_stream, step_runner,
              step_config, base_environ, start_dir):
  """Does all the logic to actually execute the step.

  This will:
    * resolve all placeholders
    * execute the step
    * calculate initial presentation status
    * parse all placeholders

  Args:
    * debug_log (Stream) - The stream we should write debugging information to.
    * step_data (StepData) - The StepData object we're going to ultimately
      return to userspace.
    * step_stream (StepStream) - The StepStream for the step we're about to
      execute.
    * step_runner (StepRunner)
    * step_config (StepConfig) - The step to run.
    * base_environ (dict|FakeEnviron) - The 'base' environment to merge the
      step_config's environmental parameters into.

  Returns (exc_info|None). Any exception which was raised while running the step
  (or None, if everything was OK).

  Side effects: populates the step_data.presentation object.
  """
  if not step_config.cmd:
    debug_log.write_line('Noop step.')
    step_data.exc_result = step_runner.run_noop(
        step_data.name_tokens, debug_log)
    _set_initial_status(step_data.presentation, step_config,
                        step_data.exc_result)
    return None

  caught = None

  exc_details = step_stream.new_log_stream('execution details')
  try:
    # Write the stack trace of the function call to the debug log
    debug_log.write_line('Stack trace for this step:')
    buffer = io.StringIO()
    traceback.print_stack(file=buffer)
    for line in buffer.getvalue().split("\n"):
      debug_log.write_line(line)

    debug_log.write_line('Prepopulating placeholder data')
    _prepopulate_placeholders(step_config, step_data)

    debug_log.write_line('Rendering input placeholders')
    rendered_step, render_err = _render_config(
        debug_log, step_data.name_tokens, step_config, step_runner, step_stream,
        base_environ, start_dir)
    if rendered_step is not None:
      _print_step(exc_details, rendered_step)

    if render_err:
      step_data.exc_result = ExecutionResult(had_exception=True)
      step_data.presentation.step_text = render_err
    else:
      debug_log.write_line('Executing step')
      try:
        step_data.exc_result = step_runner.run(
            step_data.name_tokens, debug_log, rendered_step)
      except gevent.GreenletExit:
        # Greenlet was killed while running the step
        step_data.exc_result = ExecutionResult(was_cancelled=True)
      if step_data.exc_result.retcode is not None:
        # Windows error codes such as 0xC0000005 and 0xC0000409 are much
        # easier to recognize and differentiate in hex.
        exc_details.write_line(
            'Step had exit code: %s (a.k.a. 0x%08X)' % (
              step_data.exc_result.retcode,
              step_data.exc_result.retcode & 0xffffffff))

    # Have to render presentation.status once here for the placeholders to
    # observe.
    _set_initial_status(step_data.presentation, step_config,
                        step_data.exc_result)

    if not render_err:
      debug_log.write_line('Resolving output placeholders')
      _resolve_output_placeholders(
          debug_log, step_data.name_tokens, step_config, step_data, step_runner)
  except:   # pylint: disable=bare-except
    caught = sys.exc_info()
    debug_log.write_line('Unhandled exception:')
    for line in traceback.format_exc().splitlines():
      debug_log.write_line(line)
    step_data.exc_result = attr.evolve(step_data.exc_result, had_exception=True)

  if step_data.exc_result.had_timeout:
    exc_details.write_line('Step timed out.')
  if step_data.exc_result.had_exception:
    exc_details.write_line('Step had exception.')
    for line in traceback.format_exc().splitlines():
      debug_log.write_line(line)
  if step_data.exc_result.was_cancelled:
    exc_details.write_line('Step was canceled.')
  exc_details.close()

  # Re-render the presentation status; If one of the output placeholders blew up
  # or there was otherwise something bad that happened, we should adjust
  # accordingly.
  _set_initial_status(step_data.presentation, step_config, step_data.exc_result)

  return caught


try:
  from shlex import quote as _single_arg_quote
except ImportError:
  from pipes import quote as _single_arg_quote


def _shell_quote(arg):
  """Shell-quotes a string with minimal noise such that it is still reproduced
  exactly in a bash/zsh shell.
  """
  if arg == '':
    return "''"
  # Normal shell-printable string without quotes
  if re.match(r'[-+,./0-9:@A-Z_a-z]+$', arg):
    return arg
  # Printable within regular single quotes.
  if re.match('[\040-\176]+$', arg):
    return "'%s'" % arg.replace("'", "'\\''")
  # Something complicated, printable within special escaping quotes.
  # The $'stuff' syntax makes shells interpret escape characters.
  # We promote real newlines to be their escaped counterparts, since
  # copy+pasting things with newlines is meh.
  return "$" + _single_arg_quote(arg).replace('\\', '\\\\').replace('\n', '\\n')


def _print_step(execution_log, step):
  """Prints the step command and relevant metadata.

  Intended to be similar to the information that Buildbot prints at the
  beginning of each non-annotator step.
  """
  assert isinstance(step, Step), 'expected Step, got {}'.format(step)

  execution_log.write_line('Executing command [')
  for arg in step.cmd:
    execution_log.write_line('  %r,' % arg)
  execution_log.write_line(']')

  # Apparently some recipes (I think mostly test recipes) pass commands whose
  # arguments contain literal newlines (hence the newline replacement bit).
  #
  # TODO(iannucci): Make this illegal?
  execution_log.write_line(
      'escaped for shell: %s'
      % ' '.join(_shell_quote(arg) for arg in step.cmd).replace('\n', '\\n'))

  execution_log.write_line('in dir ' + step.cwd)

  # Technically very soon _before_ the step runs, but should be insignificant.
  # Displayed in two formats because ISO format is easy to read but the deadline
  # that may show inside the LUCI_CONTEXT dict in a few lines will be a
  # timestamp.
  now = datetime.datetime.now()
  execution_log.write_line(f'at time {now.isoformat()} ({now.timestamp()})')

  # Some LUCI_CONTEXT sections may contain secrets; explicitly allow the
  # sections we know are safe.
  luci_context_allowed = ['realm', 'luciexe', 'deadline']
  luci_context_header_printed = False
  for section in luci_context_allowed:
    data = step.luci_context.get(section, None)
    if data is not None:
      if not luci_context_header_printed:
        luci_context_header_printed = True
        execution_log.write_line('LUCI_CONTEXT:')
      execution_log.write_line(
          '  %r: %r' % (section, jsonpb.MessageToDict(data)))

  # TODO(iannucci): print the DIFF against the original environment
  execution_log.write_line('full environment:')
  for key, value in sorted(step.env.items()):
    execution_log.write_line('  %s: %s' % (key, value.replace('\n', '\\n')))

  execution_log.write_line('')


def _log_crash(stream_engine, crash_location):
  # Pipe is reserved for step names, but can show up when crashing in internal
  # recipe engine functions which take the step names. Replace it with "<PIPE>"
  # so we don't double-crash when trying to report an actual problem.
  name = 'RECIPE CRASH (%s)' % (crash_location.replace("|", "<PIPE>"),)
  with stream_engine.new_step_stream((name,), False) as stream:
    stream.mark_running()
    stream.set_step_status('EXCEPTION', had_timeout=False)
    stream.write_line('The recipe has crashed at point %r!' % crash_location)
    stream.write_line('')
    _, exc, _ = sys.exc_info()
    for line in traceback.format_exception(exc):
      for part in line.splitlines():
        stream.write_line(part)
