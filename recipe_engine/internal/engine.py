# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import calendar
import collections
import datetime
import json
import os
import re
import sys
import traceback

import attr

from PB.recipe_engine import result as result_pb2

from .. import recipe_api
from .. import util
from ..step_data import StepData, ExecutionResult
from ..types import StepPresentation, thaw

from .engine_env import merge_envs
from .engine_step import StepConfig
from .exceptions import RecipeUsageError, CrashEngine
from .step_runner import Step


class RecipeEngine(object):
  """
  Knows how to execute steps emitted by a recipe, holds global state such as
  step history and build properties. Each recipe module API has a reference to
  this object.

  Recipe modules that are aware of the engine:
    * properties - uses engine.properties.
    * step - uses engine.create_step(...), and previous_step_result.
  """

  # ActiveStep is the object type that we keep in RecipeEngine._step_stack. It
  # holds:
  #
  #   step_result (StepData) - The StepData for the step
  #   step_stream (StreamEngine.StepStream) - The UI client for this step
  #   callback (func(StepPresentation, StepData)) - A user-code callback which
  #     is called when this step is finalized by the RecipeEnigne. Note that
  #     currently only parent nesting steps have callbacks populated. See
  #     the 'recipe_engine/step' module's 'nest' method.
  #
  # TODO(iannucci): use attr instead of namedtuple
  ActiveStep = collections.namedtuple(
      'ActiveStep', ('step_result', 'step_stream', 'callback'))

  def __init__(self, recipe_deps, step_runner, stream_engine, properties,
               environ, start_dir):
    """See run_steps() for parameter meanings."""
    self._recipe_deps = recipe_deps
    self._step_runner = step_runner
    self._stream_engine = stream_engine  # type: StreamEngine
    self._properties = properties
    self._environ = environ.copy()
    self._start_dir = start_dir
    self._clients = {client.IDENT: client for client in (
        recipe_api.PathsClient(start_dir),
        recipe_api.PropertiesClient(properties),
        recipe_api.SourceManifestClient(self, properties),
        recipe_api.StepClient(self),
    )}

    # A stack of ActiveStep objects, holding the most recently executed step at
    # each nest level (objects deeper in the stack have lower nest levels).
    # When we pop from this stack, we close the corresponding step stream.
    #
    # NOTE: Due to the way that steps are run in the recipe engine, only the tip
    # of this stack may be a 'real' step; i.e. anything other than the tip of
    # the stack is a parent nesting step.
    self._step_stack = []

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

  def _close_until_ns(self, namespace):
    """Close all open steps until we close all of them or until we find one
    that's a parent of of namespace.

    Example:
       open_steps = [
          name=('namespace'),
          name=('namespace', 'subspace'),
          name=('namespace', 'subspace', 'step'),
       ]
       # if the new step is ('namespace', 'subspace', 'new_step') we call:
         _close_until_ns(('namespace', 'subspace'))
         # Closes ('namespace', 'subspace', 'step')
       # if the new step is ('namespace', 'new_subspace') we call:
         _close_until_ns(('namespace',))
         # Closes ('namespace', 'subspace', 'step')
         # Closes ('namespace', 'subspace')
       # if the new step is ('bob',) we call:
         _close_until_ns(())
         # Closes ('namespace', 'subspace', 'step')
         # Closes ('namespace', 'subspace')
         # Closes ('namespace')

    Args:
      namespace (Tuple[basestring]): the namespace we're looking to get back to.
    """
    while self._step_stack:
      if self._step_stack[-1].step_result.name_tokens == namespace:
        return

      cur = self._step_stack.pop()
      if cur.callback:
        try:
          cur.callback(cur.step_result.presentation, cur.step_result)
        except:  # pylint: disable=bare-except
          cur.step_stream.set_step_status('EXCEPTION', had_timeout=False)
          name = cur.step_result.name
          _log_crash(self._stream_engine, 'Step(%r).callback' % (name,))
          raise CrashEngine(
              "Step callback for %r raised an exception" % (name,))
      cur.step_result.presentation.finalize(cur.step_stream)
      cur.step_stream.close()

  @property
  def active_step(self):
    """Returns the current ActiveStep.step_result (if there is one) or None."""
    if self._step_stack:
      return self._step_stack[-1]
    return None

  def open_parent_step(self, name_tokens, callback):
    """Opens a parent step with the given name.

    Args:
      * name_tokens (List[str]) - The name of the parent step to open.
      * callback (func(presentation, step_data)) - The callback to run when this
        parent step closes. `step_data` will have a field .children which is the
        final step_data from all the children steps.

    Returns:
      A StepData object containing an adjustable presentation.
    """
    self._close_until_ns(name_tokens[:-1])
    # TODO(iannucci): really, seriously, make new_step_stream just take
    # name_tokens.
    step_config = StepConfig(name_tokens=name_tokens)
    step_stream = self._stream_engine.new_step_stream(step_config)
    ret = StepData(name_tokens, ExecutionResult(retcode=0))
    presentation = StepPresentation(step_config.name)
    # TODO(iannucci): Don't use StepData for presentation-only steps (define
    # a different datatype). This is odd because 'StepData.children' is only
    # defined here.
    ret.children = []
    ret.presentation = presentation
    ret.finalize()
    if self._step_stack:
      self._step_stack[-1].step_result.children.append(ret)
    self._step_stack.append(self.ActiveStep(ret, step_stream, callback))
    return ret

  def run_step(self, step_config):
    """Runs a step.

    Args:
      step_config (StepConfig): The step configuration to run.

    Returns:
      A StepData object containing the result of the finished step.
    """
    # TODO(iannucci): When subannotations are handled with annotee, move
    # `allow_subannotations` into recipe_module/step.

    self._close_until_ns(step_config.name_tokens[:-1])

    # TODO(iannucci): Start with had_exception=True and overwrite when we know
    # we DIDN'T have an exception.
    ret = StepData(step_config.name_tokens, ExecutionResult())

    try:
      self._step_runner.register_step_config(step_config)
    except:
      # Test data functions are not allowed to raise exceptions. Instead of
      # letting user code catch these, we crash the test immediately.
      _log_crash(self._stream_engine, "register_step_config(%r)" % (ret.name,))
      raise CrashEngine("Registering step_config failed for %r." % (
        ret.name
      ))

    # TODO(iannucci): refactor new_step_stream to avoid passing the whole
    # step_config.
    step_stream = self._stream_engine.new_step_stream(step_config)
    debug_log = step_stream.new_log_stream('$debug')
    caught = None
    try:
      # If there's a parent step on the stack, add `ret` to its children.
      if self._step_stack:
        self._step_stack[-1].step_result.children.append(ret)

      # initialize presentation to show an exception.
      ret.presentation = StepPresentation(step_config.name)
      ret.presentation.status = 'EXCEPTION'

      self._step_stack.append(self.ActiveStep(ret, step_stream, None))

      # _run_step should never raise an exception
      caught = _run_step(
          debug_log, ret, step_stream, self._step_runner,
          step_config, self._environ, self._start_dir)

      # TODO(iannucci): remove this trigger specs crap
      if step_config.trigger_specs:
        _trigger_builds(step_stream, step_config.trigger_specs)
      # NOTE: See the accompanying note in stream.py.
      step_stream.reset_subannotation_state()

      ret.finalize()

      # If there's a buffered exception, we raise it now.
      if caught:
        # TODO(iannucci): Python3 incompatible.
        raise caught[0], caught[1], caught[2]

      if ret.presentation.status == 'SUCCESS':
        return ret

      # Otherwise, we raise an appropriate error based on
      # ret.presentation.status
      exc = {
        'FAILURE': recipe_api.StepFailure,
        'WARNING': recipe_api.StepWarning,
        'EXCEPTION': recipe_api.InfraFailure,
      }[ret.presentation.status]
      raise exc(step_config.name, ret)

    finally:
      # per sys.exc_info this is recommended in python 2.x to avoid creating
      # garbage cycles.
      del caught
      debug_log.close()

  @staticmethod
  def _setup_build_step(recipe_deps, recipe, properties, stream_engine,
                        emit_initial_properties):
    with stream_engine.make_step_stream('setup_build') as step:
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
                environ, cwd, emit_initial_properties=False, test_data=None,
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
      * emit_initial_properties (bool): If True, write the initial recipe engine
          properties in the "setup_build" step.

    Returns: result_pb2.Result

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
          recipe_deps, step_runner, stream_engine, properties, environ, cwd)
      api = recipe_obj.mk_api(engine, test_data)
      engine.initialize_path_client_HACK(api)
    except (RecipeUsageError, ImportError, AssertionError) as ex:
      _log_crash(stream_engine, 'loading recipe')
      # TODO(iannucci): differentiate the human reasons for all of these; will
      # result in expectation changes, but that should be safe in its own CL.
      result.failure.human_reason = 'Uncaught exception: ' + repr(ex)
      return result

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
        return result

    try:
      try:
        raw_result = recipe_obj.run_steps(api, engine)

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

      finally:
        # TODO(iannucci): prevent this from running any additional steps
        # (technically nest parent step callbacks COULD run steps; that should
        # be prevented).
        engine._close_until_ns(())  # pylint: disable=protected-access

    # All other exceptions are reported to the user and are fatal.
    except Exception as ex:  # pylint: disable=broad-except
      _log_crash(stream_engine, 'Uncaught exception')
      result.failure.human_reason = 'Uncaught Exception: ' + repr(ex)

    except CrashEngine as ex:
      _log_crash(stream_engine, 'Engine Crash')
      result.failure.human_reason = repr(ex)

    if result.HasField('failure'):
      return result

    try:
      result.json_result = json.dumps(raw_result, sort_keys=True)
      if raw_result is not None:
        with stream_engine.make_step_stream('recipe result') as stream:
          stream.set_build_property('$retval', result.json_result)
          stream.write_split(result.json_result)
      return result
    except Exception as ex:  # pylint: disable=broad-except
      _log_crash(stream_engine, "Serializing RunSteps retval")
      result.failure.human_reason = 'Uncaught Exception: ' + repr(ex)
      return result


def _set_initial_status(presentation, step_config, exc_result):
  """Calculates and returns a StepPresentation.status value from a StepConfig
  and an ExecutionResult.
  """
  # TODO(iannucci): make StepPresentation.status enumey instead of stringy.
  presentation.had_timeout = exc_result.had_timeout

  if exc_result.had_exception:
    presentation.status = 'EXCEPTION'
    return

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


def _resolve_output_placeholders(debug, step_config, step_data, step_runner):
  """Takes the original (unmodified by _render_placeholders) step_config and
  invokes the '.result()' method on every placeholder. This will update
  'step_data' with the results.

  `step_runner` is used for `placeholder` which should return test data
  input for the InputPlaceholder.cleanup and OutputPlaceholder.result methods.
  """
  name = step_config.name_tokens

  for itm in step_config.cmd:
    if isinstance(itm, util.Placeholder):
      test_data = step_runner.placeholder(name, itm)
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
        step_runner.handle_placeholder(name, 'stdin').enabled)

  for handle in ('stdout', 'stderr'):
    placeholder = getattr(step_config, handle)
    if placeholder:
      debug.write_line('  finding result of %s: %r' % (handle, placeholder))
      test_data = step_runner.handle_placeholder(name, handle)
      setattr(step_data, handle, placeholder.result(
          step_data.presentation, test_data))


def _render_config(debug, step_config, step_runner, step_stream, environ,
                   start_dir):
  """Returns a step_runner.Step which is ready for consumption by
  StepRunner.run.

  `step_runner` is used for `placeholder` and `handle_placeholder`
  which should return test data input for the Placeholder.render method
  (or an empty test data object).
  """
  name = step_config.name_tokens

  cmd = []
  debug.write_line('rendering placeholders')
  for itm in step_config.cmd:
    if isinstance(itm, util.Placeholder):
      debug.write_line('  %r' % (itm,))
      cmd.extend(itm.render(step_runner.placeholder(name, itm)))
    else:
      cmd.append(itm)

  handles = {}
  debug.write_line('rendering std handles')
  for handle in ('stdout', 'stderr', 'stdin'):
    placeholder = getattr(step_config, handle)
    if placeholder:
      debug.write_line('  %s: %r' % (handle, placeholder))
      placeholder.render(step_runner.handle_placeholder(name, handle))
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
  if not step_runner.isabs(name, cwd):
    debug.write_line('  not absolute: %r' % (cwd))
    return None
  if not step_runner.isdir(name, cwd):
    debug.write_line('  not a directory: %r' % (cwd))
    return None
  if not step_runner.access(name, cwd, os.R_OK):
    debug.write_line('  no read perms: %r' % (cwd))
    return None

  path = env.get('PATH', '').split(pathsep)
  debug.write_line('resolving cmd0 %r' % (cmd[0],))
  debug.write_line('  in PATH: %s' % (path,))
  debug.write_line('  with cwd: %s' % (cwd,))
  cmd0 = step_runner.resolve_cmd0(name, debug, cmd[0], cwd, path)
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
        step_config.name_tokens, debug_log)
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
        debug_log, step_config, step_runner, step_stream, base_environ,
        start_dir)
    if not rendered_step:
      step_data.exc_result = ExecutionResult(had_exception=True)
    else:
      _print_step(exc_details, rendered_step)

      debug_log.write_line('Executing step')
      step_data.exc_result = step_runner.run(
          step_config.name_tokens, debug_log, rendered_step)
      if step_data.exc_result.retcode is not None:
        # Windows error codes such as 0xC0000005 and 0xC0000409 are much
        # easier to recognize and differentiate in hex. In order to print them
        # as unsigned hex we need to add 4 Gig to them.
        #
        # To make this conditional on platform we'd have to plumb through the
        # simulated platform (or make a new StepRunner method) for this; we've
        # opted to just unconditionally print both error representations.
        exc_details.write_line(
            'Step had exit code: %s (a.k.a. 0x%08X)' % (
              step_data.exc_result.retcode,
              step_data.exc_result.retcode + (1 << 32),))

    # Have to render presentation.status once here for the placeholders to
    # observe.
    _set_initial_status(step_data.presentation, step_config,
                        step_data.exc_result)

    if rendered_step:
      debug_log.write_line('Resolving output placeholders')
      _resolve_output_placeholders(debug_log, step_config, step_data,
                                   step_runner)
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
  exc_details.close()

  # Re-render the presentation status; If one of the output placeholders blew up
  # or there was otherwise something bad that happened, we should adjust
  # accordingly.
  _set_initial_status(step_data.presentation, step_config, step_data.exc_result)

  return caught


def _trigger_builds(step_stream, trigger_specs):
  # TODO(iannucci): remove this
  def _normalize_change(change):
    assert isinstance(change, dict), 'Change is not a dict'
    change = change.copy()

    # Convert when_timestamp to UNIX timestamp.
    when = change.get('when_timestamp')
    if isinstance(when, datetime.datetime):
      when = calendar.timegm(when.utctimetuple())
      change['when_timestamp'] = when

    return change

  assert trigger_specs is not None
  for trig in trigger_specs:
    builder_name = trig.builder_name
    if not builder_name:
      raise ValueError('Trigger spec: builder_name is not set')

    changes = trig.buildbot_changes or []
    assert isinstance(changes, list), 'buildbot_changes must be a list'

    changes = map(_normalize_change, changes)

    step_stream.trigger(json.dumps(thaw({
        'builderNames': [builder_name],
        'bucket': trig.bucket,
        'changes': changes,
        # if True and triggering fails asynchronously, fail entire build.
        'critical': trig.critical,
        'properties': trig.properties,
        'tags': trig.tags,
    }), sort_keys=True))


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

  # Apparently some recipes (I think mostly test recipes) pass commands whose
  # arguments contain literal newlines (hence the newline replacement bit).
  #
  # TODO(iannucci): Make this illegal?
  execution_log.write_line(
      ' '.join(map(_shell_quote, step.cmd)).replace('\n', '\\n'))

  execution_log.write_line('in dir ' + step.cwd)

  if step.timeout:
    execution_log.write_line('  timeout: %d secs' % (step.timeout,))

  # TODO(iannucci): print the DIFF against the original environment
  execution_log.write_line('full environment:')
  for key, value in sorted(step.env.items()):
    execution_log.write_line('  %s: %s' % (key, value.replace('\n', '\\n')))

  execution_log.write_line('')


def _log_crash(stream_engine, crash_location):
  name = 'RECIPE CRASH (%s)' % (crash_location,)
  with stream_engine.make_step_stream(name) as stream:
    stream.set_step_status('EXCEPTION', had_timeout=False)
    stream.write_line('The recipe has crashed at point %r!' % crash_location)
    stream.write_line('')
    for line in traceback.format_exc().splitlines():
      stream.write_line(line)
