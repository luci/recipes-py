# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Entry point for running recipes for real (not in testing mode)."""

import collections
import json
import logging
import os
import sys
import traceback

from google.protobuf import json_format as jsonpb

from recipe_engine.third_party import subprocess42

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

from PB.recipe_engine import result as result_pb2

from .... import recipe_api
from .... import types
from .... import util

from ...exceptions import RecipeUsageError
from ...recipe_deps import Recipe
from ...step_runner import SubprocessStepRunner
from ...stream import AnnotatorStreamEngine, StreamEngineInvariants


# TODO(martiniss): Remove this
RecipeResult = collections.namedtuple('RecipeResult', 'result')


# TODO(dnj): Replace "properties" with a generic runtime instance. This instance
# will be used to seed recipe clients and expanded to include managed runtime
# entities.
def run_steps(recipe_deps, properties, stream_engine, step_runner,
              emit_initial_properties=False):
  """Runs a recipe (given by the 'recipe' property) for real.

  Args:
    * recipe_deps (RecipeDeps) - The loaded recipe repo dependencies.
    * properties: a dictionary of properties to pass to the recipe.  The
      'recipe' property defines which recipe to actually run.
    * stream_engine: the StreamEngine to use to create individual step streams.
    * step_runner: The StepRunner to use to 'actually run' the steps.
    * emit_initial_properties (bool): If True, write the initial recipe engine
        properties in the "setup_build" step.

  Returns: result_pb2.Result
  """
  with stream_engine.make_step_stream('setup_build') as s:
    if emit_initial_properties:
      for key in sorted(properties.iterkeys()):
        s.set_build_property(key, json.dumps(properties[key], sort_keys=True))

    engine = RecipeEngine(
        recipe_deps, step_runner, properties, os.environ)

    assert 'recipe' in properties
    recipe = properties['recipe']

    run_recipe_help_lines = [
        'To repro this locally, run the following line from the root of a %r'
          ' checkout:' % (recipe_deps.main_repo.name),
        '',
        '%s run --properties-file - %s <<EOF' % (
            os.path.join(
              '.', recipe_deps.main_repo.simple_cfg.recipes_path, 'recipes.py'),
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

    with s.new_log_stream('run_recipe') as l:
      for line in run_recipe_help_lines:
        l.write_line(line)

    # Find and load the recipe to run.
    try:
      # This does all loading and importing of the recipe script.
      recipe_obj = recipe_deps.main_repo.recipes[recipe]
      # Make sure `global_symbols` (which is a cached execfile of the recipe
      # python file) executes here so that we can correctly catch any
      # RecipeUsageError exceptions which exec'ing it may cause.
      # TODO(iannucci): rethink how all this exception reporting stuff should
      # work.
      _ = recipe_obj.global_symbols
      s.write_line('Running recipe with %s' % (properties,))
      s.add_step_text('running recipe: "%s"' % recipe)
    except (RecipeUsageError, ImportError, AssertionError) as e:
      for line in str(e).splitlines():
        s.add_step_text(line)
      s.set_step_status('EXCEPTION')
      return result_pb2.Result(
          failure=result_pb2.Failure(
              human_reason=str(e),
              exception=result_pb2.Exception(
                traceback=traceback.format_exc().splitlines()
              )))

  # The engine will use step_runner to run the steps, and the step_runner in
  # turn uses stream_engine internally to build steam steps IO.
  return engine.run(recipe_obj)


# Return value of run_steps and RecipeEngine.run.  Just a container for the
# literal return value of the recipe.
# TODO(martiniss): remove this
RecipeResult = collections.namedtuple('RecipeResult', 'result')


class RecipeEngine(object):
  """
  Knows how to execute steps emitted by a recipe, holds global state such as
  step history and build properties. Each recipe module API has a reference to
  this object.

  Recipe modules that are aware of the engine:
    * properties - uses engine.properties.
    * step - uses engine.create_step(...), and previous_step_result.
  """

  ActiveStep = collections.namedtuple('ActiveStep', (
      'config', 'step_result', 'open_step'))

  def __init__(self, recipe_deps, step_runner, properties, environ):
    """See run_steps() for parameter meanings."""
    self._recipe_deps = recipe_deps
    self._step_runner = step_runner
    self._properties = properties
    self._environ = environ.copy()
    self._clients = {client.IDENT: client for client in (
        recipe_api.PathsClient(),
        recipe_api.PropertiesClient(self),
        recipe_api.SourceManifestClient(self, properties),
        recipe_api.StepClient(self),
    )}

    # A stack of ActiveStep objects, holding the most recently executed step at
    # each nest level (objects deeper in the stack have lower nest levels).
    # When we pop from this stack, we close the corresponding step stream.
    self._step_stack = []

  @property
  def properties(self):
    return self._properties

  @property
  def environ(self):
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

    However, we would like to:
      * Make the 'api' wholly internal to the `RecipeScript.run_steps` function.
      * Eventually simplify the 'paths' system, whose whole complexity exists to
        facilitate 'pure-data' config.py processing, which is also going to be
        deprecated in favor of protos and removal of the config subsystem.

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
      if self._step_stack[-1].config.name_tokens == namespace:
        return

      cur = self._step_stack.pop()
      if cur.step_result:
        cur.step_result.presentation.finalize(cur.open_step.stream)
      cur.open_step.finalize()

  @property
  def active_step(self):
    """Returns the current ActiveStep (if there is one) or None."""
    if self._step_stack:
      return self._step_stack[-1]
    return None

  def run_step(self, step_config):
    """
    Runs a step.

    Args:
      step_config (recipe_api.StepClient.StepConfig): The step configuration to
        run.

    Returns:
      A StepData object containing the result of running the step.
    """
    with util.raises((recipe_api.StepFailure, OSError),
                     self._step_runner.stream_engine):
      step_result = None

      self._close_until_ns(step_config.name_tokens[:-1])

      open_step = self._step_runner.open_step(step_config)
      self._step_stack.append(self.ActiveStep(
          config=step_config,
          step_result=None,
          open_step=open_step))

      step_result = open_step.run()
      self._step_stack[-1] = (
          self._step_stack[-1]._replace(step_result=step_result))

      if step_result.presentation.status == 'SUCCESS':
        return step_result

      exc = recipe_api.StepFailure
      if step_result.presentation.status == 'EXCEPTION':
        exc = recipe_api.InfraFailure

      if step_result.retcode <= -100:
        # Windows error codes such as 0xC0000005 and 0xC0000409 are much
        # easier to recognize and differentiate in hex. In order to print them
        # as unsigned hex we need to add 4 Gig to them.
        error_number = "0x%08X" % (step_result.retcode + (1 << 32))
      else:
        error_number = "%d" % step_result.retcode
      self._step_stack[-1].open_step.stream.write_line(
          'step returned non-zero exit code: %s' % error_number)

      raise exc(step_config.name, step_result)

  def run(self, recipe, test_data=None):
    """Run a recipe.

    This function blocks until recipe finishes.
    It mainly executes the recipe, and has some exception handling logic.

    Args:
      * recipe (Recipe): The recipe to run.
      * test_data (None|TestData): The test data for this recipe run.

    Returns:
      result_pb2.Result which has return value or status code and exception.
    """
    assert isinstance(recipe, Recipe), type(recipe)
    result = None
    plain_failure_result = lambda f: result_pb2.Result(
      failure=result_pb2.Failure(
          human_reason=f.reason,
          failure=result_pb2.StepFailure(
              step=f.name,
          )))
    infra_failure_result = lambda f: result_pb2.Result(
      failure=result_pb2.Failure(
          human_reason=f.reason,
          exception=result_pb2.Exception(
              traceback=traceback.format_exc().splitlines()
          )))


    with self._step_runner.run_context():
      try:
        try:
          raw_result = recipe.run_steps(self, test_data)
          result = result_pb2.Result(json_result=json.dumps(raw_result))
        finally:
          self._close_until_ns(())

      except recipe_api.InfraFailure as f:
        result = infra_failure_result(f)

      except recipe_api.AggregatedStepFailure as f:
        if f.result.contains_infra_failure:
          result = infra_failure_result(f)
        else:
          result = plain_failure_result(f)

      except recipe_api.StepFailure as f:
        result = plain_failure_result(f)

      except types.StepDataAttributeError as ex:
        result = result_pb2.Result(
            failure=result_pb2.Failure(
                human_reason=ex.message,
                step_data=result_pb2.StepData(
                    step=ex.step,
                )))

        # Let the step runner run_context decide what to do.
        raise

      except subprocess42.TimeoutExpired as ex:
        result = result_pb2.Result(
          failure=result_pb2.Failure(
              human_reason="Step time out: %r" % ex,
              timeout= result_pb2.Timeout(
                  timeout_s=ex.timeout
              )))

      except Exception as ex:
        result = result_pb2.Result(
          failure=result_pb2.Failure(
              human_reason="Uncaught Exception: %r" % ex,
              exception=result_pb2.Exception(
                  traceback=traceback.format_exc().splitlines()
              )))

        # Let the step runner run_context decide what to do.
        raise

    return result


def handle_recipe_return(recipe_result, result_filename, stream_engine):
  if result_filename:
    with open(result_filename, 'w') as fil:
      fil.write(jsonpb.MessageToJson(
          recipe_result, including_default_value_fields=True))

  if recipe_result.json_result:
    with stream_engine.make_step_stream('recipe result') as s:
      with s.new_log_stream('result') as l:
        l.write_split(recipe_result.json_result)

  if recipe_result.HasField('failure'):
    f = recipe_result.failure
    if f.HasField('exception'):
      with stream_engine.make_step_stream('Uncaught Exception') as s:
        s.set_step_status('EXCEPTION')
        s.add_step_text(f.human_reason)
        with s.new_log_stream('exception') as l:
          for line in f.exception.traceback:
            l.write_line(line)
    # TODO(martiniss): Remove this code once calling code handles these states
    elif f.HasField('timeout'):
      with stream_engine.make_step_stream('Step Timed Out') as s:
        s.set_step_status('FAILURE')
        with s.new_log_stream('timeout_s') as l:
          l.write_line(f.timeout.timeout_s)
    elif f.HasField('step_data'):
      with stream_engine.make_step_stream('Invalid Step Data Access') as s:
        s.set_step_status('FAILURE')
        with s.new_log_stream('step') as l:
          l.write_line(f.step_data.step)

    with stream_engine.make_step_stream('Failure reason') as s:
      s.set_step_status('FAILURE')
      with s.new_log_stream('reason') as l:
        l.write_split(f.human_reason)

    return 1

  return 0


def main(args):
  if args.props:
    for p in args.props:
      args.properties.update(p)

  properties = args.properties

  properties['recipe'] = args.recipe

  properties = util.strip_unicode(properties)

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'

  # TODO(iannucci): this is horrible; why do we want to set a workdir anyway?
  # Shouldn't the caller of recipes just CD somewhere if they want a different
  # workdir?
  workdir = (args.workdir or
      os.path.join(RECIPE_ENGINE_PATH[0], os.path.pardir, 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  old_cwd = os.getcwd()
  os.chdir(workdir)

  stream_engine = AnnotatorStreamEngine(sys.stdout)

  # This only applies to 'annotation' mode and will go away with build.proto.
  # It is slightly hacky, but this property is the officially documented way
  # to communicate to the recipes that they are in LUCI-mode, so we might as
  # well use it.
  emit_initial_properties = bool(
    properties.
    get('$recipe_engine/runtime', {}).
    get('is_luci', False)
  )

  # Have a top-level set of invariants to enforce StreamEngine expectations.
  with StreamEngineInvariants.wrap(stream_engine) as stream_engine:
    try:
      ret = run_steps(
          args.recipe_deps, properties, stream_engine,
          SubprocessStepRunner(stream_engine),
          emit_initial_properties=emit_initial_properties)
    finally:
      os.chdir(old_cwd)

    return handle_recipe_return(ret, args.output_result_json, stream_engine)
