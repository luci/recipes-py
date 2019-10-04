# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import calendar
import datetime
import json
import os
import re
import sys
import traceback

from contextlib import contextmanager

import attr
import gevent
import gevent.local

from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from .. import recipe_api
from .. import util
from ..step_data import StepData, ExecutionResult
from ..types import StepPresentation, thaw

from .engine_env import merge_envs
from .exceptions import RecipeUsageError, CrashEngine
from .step_runner import Step
from .resource_semaphore import ResourceWaiter


@attr.s(frozen=True, slots=True, repr=False)
class _ActiveStep(object):
  """The object type that we keep in RecipeEngine._step_stack."""
  step_data = attr.ib()    # type: StepData
  step_stream = attr.ib()  # type: StepStream
  is_parent = attr.ib()    # type: bool

  children_steps = attr.ib(factory=list)  # type: List[StepData]
  greenlets = attr.ib(factory=list)       # type: List[gevent.Greenlet]

  def close(self):
    """If step_data is set, finalizes its StepPresentation with
    self.step_stream, then closes self.step_stream.
    """
    gevent.wait(self.greenlets)
    if self.step_data:
      self.step_data.presentation.finalize(self.step_stream)
      self.step_stream.close()


class RecipeEngine(object):
  """
  Knows how to execute steps emitted by a recipe, holds global state such as
  step history and build properties. Each recipe module API has a reference to
  this object.

  Recipe modules that are aware of the engine:
    * properties - uses engine.properties.
    * step - uses engine.create_step(...), and previous_step_result.
  """

  def __init__(self, recipe_deps, step_runner, stream_engine, properties,
               environ, start_dir, num_logical_cores, memory_mb):
    """See run_steps() for parameter meanings."""
    self._recipe_deps = recipe_deps
    self._step_runner = step_runner
    self._stream_engine = stream_engine  # type: StreamEngine
    self._properties = properties
    self._environ = environ.copy()
    self._start_dir = start_dir
    self._clients = {client.IDENT: client for client in (
        recipe_api.ConcurrencyClient(
            stream_engine.supports_concurrency,
            self.spawn_greenlet),
        recipe_api.PathsClient(start_dir),
        recipe_api.PropertiesClient(properties),
        recipe_api.SourceManifestClient(self, properties),
        recipe_api.StepClient(self),
    )}

    self._resource = ResourceWaiter(num_logical_cores * 1000, memory_mb)

    # A greenlet-local store which holds a stack of _ActiveStep objects, holding
    # the most recently executed step at each nest level (objects deeper in the
    # stack have lower nest levels). When we pop from this stack, we close the
    # corresponding step stream.
    #
    # NOTE: Due to the way that steps are run in the recipe engine, only the tip
    # of this stack may be a 'real' step; i.e. anything other than the tip of
    # the stack is a parent nesting step.
    self._step_stack_storage = gevent.local.local()
    self._step_stack_storage.steps = [
      _ActiveStep(None, None, True)  # "root" parent
    ]

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

  def resolve_requirement(self, req):
    """Resolves a requirement or raises ValueError if it cannot be resolved.

    Args:
      * req (_UnresolvedRequirement): The requirement to resolve.

    Returns the resolved requirement.
    Raises ValueError if the requirement cannot be satisfied.
    """
    # pylint: disable=protected-access
    assert isinstance(req, recipe_api._UnresolvedRequirement)
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

  def set_manifest_link(self, name, sha256, url):
    """Sets 'manifest_link' on the currently active step.

    DEPRECATED: re-invent manifest link with build.proto.

    Raises ValueError if there is no current step.
    """
    if not self.active_step:
      raise ValueError('No active step')
    self._step_stack[-1].step_stream.set_manifest_link(name, sha256, url)

  def spawn_greenlet(self, func, args, kwargs, greenlet_name):
    """Returns a gevent.Greenlet which has been initialized with the correct
    greenlet-local-storage state.

    Args:
      * greenlet_name (str|None) - If non-None, assign this to the greenlet's
        name.
    """
    self.close_non_parent_step()

    current_step = self._step_stack[-1]
    def _runner():
      self._step_stack_storage.steps = [current_step]
      try:
        return func(*args, **kwargs)
      finally:
        self.close_non_parent_step()
    ret = gevent.spawn(_runner)
    if greenlet_name is not None:
      ret.name = greenlet_name
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
      step_data.presentation = presentation
      step_data.finalize()
      self._step_stack[-1].children_steps.append(step_data)

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
      yield presentation, active_step.children_steps
    finally:
      try:
        self.close_non_parent_step()
        self._step_stack.pop().close()
      except:
        _log_crash(self._stream_engine, "parent_step.close(%r)" % (name_tokens))
        raise CrashEngine("Closing parent step %r failed." % (name_tokens))

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

    step_stream = self._stream_engine.new_step_stream(
        name_tokens, step_config.allow_subannotations)
    caught = None
    try:
      # If there's a parent step on the stack, add `ret` to its children.
      self._step_stack[-1].children_steps.append(ret)

      # initialize presentation to show an exception.
      ret.presentation = StepPresentation(step_config.name)
      ret.presentation.status = 'EXCEPTION'

      self._step_stack.append(_ActiveStep(ret, step_stream, False))

      # _run_step should never raise an exception, except for GreenletExit
      try:
        def _if_blocking():
          step_stream.set_summary_markdown(
              'Waiting for resources: `%s`' % (step_config.cost,))
        with self._resource.wait_for(step_config.cost, _if_blocking):
          step_stream.mark_running()
          debug_log = step_stream.new_log_stream('$debug')
          try:
            caught = _run_step(
                debug_log, ret, step_stream, self._step_runner, step_config,
                self._environ, self._start_dir)
          finally:
            # NOTE: See the accompanying note in stream.py.
            step_stream.reset_subannotation_state()
            debug_log.close()
      except gevent.GreenletExit:
        ret.exc_result = attr.evolve(ret.exc_result, was_cancelled=True)

      ret.finalize()

      # If there's a buffered exception, we raise it now.
      if caught:
        # TODO(iannucci): Python3 incompatible.
        raise caught[0], caught[1], caught[2]

      # If the step was cancelled, raise GreenletExit.
      if ret.exc_result.was_cancelled:
        raise gevent.GreenletExit()

      if ret.presentation.status == 'SUCCESS':
        return ret

      # Otherwise, we raise an appropriate error based on
      # ret.presentation.status
      exc = {
        'FAILURE': recipe_api.StepFailure,
        'WARNING': recipe_api.StepWarning,
        'EXCEPTION': recipe_api.InfraFailure,
      }[ret.presentation.status]
      # TODO(iannucci): Use '|' instead of '.'
      raise exc('.'.join(name_tokens), ret)

    finally:
      # per sys.exc_info this is recommended in python 2.x to avoid creating
      # garbage cycles.
      del caught

  @staticmethod
  def _setup_build_step(recipe_deps, recipe, properties, stream_engine,
                        emit_initial_properties):
    with stream_engine.new_step_stream(('setup_build',), False) as step:
      step.mark_running()
      if emit_initial_properties:
        for key in sorted(properties.iterkeys()):
          step.set_build_property(
              key, json.dumps(properties[key], sort_keys=True))

      run_recipe_help_lines = [
          'To repro this locally, run the following line from the root of a %r'
            ' checkout:' % (recipe_deps.main_repo.name),
          '',
          '%s run --properties-file - %s <<EOF' % (
              os.path.join(
                  '.', recipe_deps.main_repo.simple_cfg.recipes_path,
                  'recipes.py'),
              recipe),
      ]
      run_recipe_help_lines.extend(
          json.dumps(properties, indent=2).splitlines())
      run_recipe_help_lines += [
          'EOF',
          '',
          'To run on Windows, you can put the JSON in a file and redirect the',
          'contents of the file into run_recipe.py, with the < operator.',
      ]

      with step.new_log_stream('run_recipe') as log:
        for line in run_recipe_help_lines:
          log.write_line(line)

      step.write_line('Running recipe with %s' % (properties,))
      step.add_step_text('running recipe: "%s"' % recipe)

  @classmethod
  def run_steps(cls, recipe_deps, properties, stream_engine, step_runner,
                environ, cwd, num_logical_cores, memory_mb,
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
      * num_logical_cores (int): The number of logical CPU cores to assume the
        machine has.
      * memory_mb (int): The amount of memory to assume the machine has, in MiB.
      * emit_initial_properties (bool): If True, write the initial recipe engine
          properties in the "setup_build" step.

    Returns a 2-tuple of:
      * result_pb2.Result
      * The tuple containing exception info if there is an uncaught exception
          triggered by recipe code or None

    Does NOT raise exceptions.
    """
    result = result_pb2.Result()

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
          recipe_deps, step_runner, stream_engine, properties, environ, cwd,
          num_logical_cores, memory_mb)
      api = recipe_obj.mk_api(engine, test_data)
      engine.initialize_path_client_HACK(api)
    except (RecipeUsageError, ImportError, AssertionError) as ex:
      _log_crash(stream_engine, 'loading recipe')
      # TODO(iannucci): differentiate the human reasons for all of these; will
      # result in expectation changes, but that should be safe in its own CL.
      result.failure.human_reason = 'Uncaught exception: ' + repr(ex)
      return result, None

    # TODO(iannucci): Don't skip this during tests (but maybe filter it out from
    # expectations).
    if not skip_setup_build:
      try:
        cls._setup_build_step(
            recipe_deps, recipe, properties, stream_engine,
            emit_initial_properties)
      except Exception as ex:
        _log_crash(stream_engine, 'setup_build')
        result.failure.human_reason = 'Uncaught Exception: ' + repr(ex)
        return result, None

    try:
      try:
        try:
          raw_result = recipe_obj.run_steps(api, engine)
          if raw_result is not None:
            if isinstance(raw_result, result_pb2.RawResult):
              if raw_result.status != common_pb2.SUCCESS:
                result.failure.human_reason = raw_result.summary_markdown
                if raw_result.status != common_pb2.INFRA_FAILURE:
                  result.failure.failure.SetInParent()
            # Notify user that they used the wrong recipe return type.
            else:
                result.failure.human_reason = ('"%r" is not a valid '
                  'return type for recipes. Did you mean to use "RawResult"?'
                  % (type(raw_result)))
                result.failure.failure.SetInParent()
        finally:
          # TODO(iannucci): give this more symmetry with parent_step
          engine.close_non_parent_step()
          engine._step_stack[-1].close()   # pylint: disable=protected-access

      # TODO(iannucci): the differentiation here is a bit weird
      except recipe_api.InfraFailure as ex:
        result.failure.human_reason = ex.reason

      except recipe_api.AggregatedStepFailure as ex:
        result.failure.human_reason = ex.reason
        if not ex.result.contains_infra_failure:
          result.failure.failure.SetInParent()

      except recipe_api.StepFailure as ex:
        result.failure.human_reason = ex.reason
        result.failure.failure.SetInParent()

    # All other exceptions are reported to the user and are fatal.
    except Exception as ex:  # pylint: disable=broad-except
      _log_crash(stream_engine, 'Uncaught exception')
      result.failure.human_reason = 'Uncaught Exception: ' + repr(ex)
      return result, sys.exc_info()

    except CrashEngine as ex:
      _log_crash(stream_engine, 'Engine Crash')
      result.failure.human_reason = repr(ex)

    return result, None


def _set_initial_status(presentation, step_config, exc_result):
  """Calculates and returns a StepPresentation.status value from a StepConfig
  and an ExecutionResult.
  """
  # TODO(iannucci): make StepPresentation.status enumey instead of stringy.
  presentation.had_timeout = exc_result.had_timeout

  if exc_result.had_exception:
    presentation.status = 'EXCEPTION'
    return

  # TODO(iannucci): Add a real status for CANCELED?

  if (step_config.ok_ret is step_config.ALL_OK or
      exc_result.retcode in step_config.ok_ret):
    presentation.status = 'SUCCESS'
    return

  presentation.status = 'EXCEPTION' if step_config.infra_step else 'FAILURE'


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
  """Returns a step_runner.Step which is ready for consumption by
  StepRunner.run.

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
      handles[handle] = getattr(step_stream, handle)

  debug.write_line('merging envs')
  pathsep = step_config.env_suffixes.pathsep
  # TODO(iannucci): remove second return value from merge_envs, it's not needed
  # any more.
  env, _ = merge_envs(environ,
      step_config.env,
      step_config.env_prefixes.mapping,
      step_config.env_suffixes.mapping,
      pathsep)

  debug.write_line('checking cwd: %r' % (step_config.cwd,))
  cwd = step_config.cwd or start_dir
  if not step_runner.isabs(name_tokens, cwd):
    debug.write_line('  not absolute: %r' % (cwd))
    return None
  if not step_runner.isdir(name_tokens, cwd):
    debug.write_line('  not a directory: %r' % (cwd))
    return None
  if not step_runner.access(name_tokens, cwd, os.R_OK):
    debug.write_line('  no read perms: %r' % (cwd))
    return None

  path = env.get('PATH', '').split(pathsep)
  debug.write_line('resolving cmd0 %r' % (cmd[0],))
  debug.write_line('  in PATH: %s' % (path,))
  debug.write_line('  with cwd: %s' % (cwd,))
  cmd0 = step_runner.resolve_cmd0(name_tokens, debug, cmd[0], cwd, path)
  if cmd0 is None:
    debug.write_line('failed to resolve cmd0')
    return None
  debug.write_line('resolved cmd0: %r' % (cmd0,))

  return Step(
      cmd=(cmd0,) + tuple(cmd[1:]),
      cwd=cwd,
      env=env,
      timeout=step_config.timeout,
      **handles)


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
    debug_log.write_line('Prepopulating placeholder data')
    _prepopulate_placeholders(step_config, step_data)

    debug_log.write_line('Rendering input placeholders')
    rendered_step = _render_config(
        debug_log, step_data.name_tokens, step_config, step_runner, step_stream,
        base_environ, start_dir)
    if not rendered_step:
      step_data.exc_result = ExecutionResult(had_exception=True)
    else:
      _print_step(exc_details, rendered_step)

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

    if rendered_step:
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
  if step_data.exc_result.was_cancelled:
    exc_details.write_line('Step was cancelled.')
  exc_details.close()

  # Re-render the presentation status; If one of the output placeholders blew up
  # or there was otherwise something bad that happened, we should adjust
  # accordingly.
  _set_initial_status(step_data.presentation, step_config, step_data.exc_result)

  return caught


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
  return "$'%s'" % arg.encode('string_escape')


def _print_step(execution_log, step):
  """Prints the step command and relevant metadata.

  Intended to be similar to the information that Buildbot prints at the
  beginning of each non-annotator step.
  """
  assert isinstance(step, Step)

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
      % ' '.join(map(_shell_quote, step.cmd)).replace('\n', '\\n'))

  execution_log.write_line('in dir ' + step.cwd)

  if step.timeout:
    execution_log.write_line('  timeout: %d secs' % (step.timeout,))

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
    for line in traceback.format_exc().splitlines():
      stream.write_line(line)
