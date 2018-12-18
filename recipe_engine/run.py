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

from . import loader
from . import recipe_api
from . import recipe_test_api
from . import types
from . import util

from . import env

import argparse  # this is vendored
import subprocess42

from . import result_pb2

from google.protobuf import json_format as jsonpb


SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))


# TODO(martiniss): Remove this
RecipeResult = collections.namedtuple('RecipeResult', 'result')


# TODO(dnj): Replace "properties" with a generic runtime instance. This instance
# will be used to seed recipe clients and expanded to include managed runtime
# entities.
def run_steps(properties, stream_engine, step_runner, universe_view,
              engine_flags=None, emit_initial_properties=False):
  """Runs a recipe (given by the 'recipe' property) for real.

  Args:
    properties: a dictionary of properties to pass to the recipe.  The
      'recipe' property defines which recipe to actually run.
    stream_engine: the StreamEngine to use to create individual step streams.
    step_runner: The StepRunner to use to 'actually run' the steps.
    universe_view: The RecipeUniverse to use to load the recipes & modules.
    engine_flags: Any flags which modify engine behavior. See arguments.proto.
    emit_initial_properties (bool): If True, write the initial recipe engine
        properties in the "setup_build" step.

  Returns: result_pb2.Result
  """
  with stream_engine.make_step_stream('setup_build') as s:
    if emit_initial_properties:
      for key in sorted(properties.iterkeys()):
        s.set_build_property(key, json.dumps(properties[key], sort_keys=True))

    engine = RecipeEngine(
        step_runner, properties, os.environ, universe_view, engine_flags)

    # Create all API modules and top level RunSteps function.  It doesn't launch
    # any recipe code yet; RunSteps needs to be called.
    api = None

    assert 'recipe' in properties
    recipe = properties['recipe']

    root_package = universe_view.universe.package_deps.root_package
    run_recipe_help_lines = [
        'To repro this locally, run the following line from the root of a %r'
          ' checkout:' % (root_package.name),
        '',
        '%s run --properties-file - %s <<EOF' % (
            os.path.join( '.', root_package.relative_recipes_dir, 'recipes.py'),
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
      recipe_script = universe_view.load_recipe(recipe, engine=engine)
      s.write_line('Running recipe with %s' % (properties,))

      api = loader.create_recipe_api(
          universe_view.universe.package_deps.root_package,
          recipe_script.LOADED_DEPS,
          recipe_script.path,
          engine,
          recipe_test_api.DisabledTestData())

      s.add_step_text('running recipe: "%s"' % recipe)
    except (loader.LoaderError, ImportError, AssertionError) as e:
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
  return engine.run(recipe_script, api)


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

  def __init__(self, step_runner, properties, environ, universe_view,
               engine_flags=None):
    """See run_steps() for parameter meanings."""
    self._step_runner = step_runner
    self._properties = properties
    self._environ = environ.copy()
    self._universe_view = universe_view
    self._clients = {client.IDENT: client for client in (
        recipe_api.PathsClient(),
        recipe_api.PropertiesClient(self),
        recipe_api.SourceManifestClient(self, properties),
        recipe_api.StepClient(self),
    )}
    self._engine_flags = engine_flags

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

  @property
  def universe(self):
    return self._universe_view.universe

  def _close_through_level(self, level):
    """Close all open steps whose nest level is >= the supplied level.

    Args:
      level (int): the nest level to close through.
    """
    while self._step_stack and self._step_stack[-1].config.nest_level >= level:
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

  def _get_client(self, name):
    """Returns: the client instance for name, or None if not such client exists.

    Args:
      name (str): The name of the client instance to retrieve.
    """
    return self._clients.get(name)

  def run_step(self, step_config):
    """
    Runs a step.

    Args:
      step_config (recipe_api.StepClient.StepConfig): The step configuration to
        run.

    Returns:
      A StepData object containing the result of running the step.
    """
    if '|' in step_config.name:
      raise ValueError(
          'Pipe character ("|") cannot be used in a step name. '
          'It is reserved as a parent-child step separator.')

    with util.raises((recipe_api.StepFailure, OSError),
                     self._step_runner.stream_engine):
      step_result = None

      self._close_through_level(step_config.nest_level)

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

  def run(self, recipe_script, api):
    """Run a recipe represented by a recipe_script object.

    This function blocks until recipe finishes.
    It mainly executes the recipe, and has some exception handling logic.

    Args:
      recipe_script: The recipe to run, as represented by a RecipeScript object.
      api: The api, with loaded module dependencies.
           Used by the some special modules.

    Returns:
      result_pb2.Result which has return value or status code and exception.
    """
    self._get_client('paths')._initialize_with_recipe_api(api)
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
          recipe_result = recipe_script.run(api, self.properties, self.environ)
          result = result_pb2.Result(json_result=json.dumps(recipe_result))
        finally:
          self._close_through_level(0)

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


def add_subparser(parser):
  def properties_file_type(filename):
    with (sys.stdin if filename == '-' else open(filename)) as f:
      obj = json.load(f)
      if not isinstance(obj, dict):
        raise argparse.ArgumentTypeError(
          'must contain a JSON object, i.e. `{}`.')
      return obj

  def parse_prop(prop):
    key, val = prop.split('=', 1)
    try:
      val = json.loads(val)
    except (ValueError, SyntaxError):
      pass  # If a value couldn't be evaluated, keep the string version
    return {key: val}

  def properties_type(value):
    obj = json.loads(value)
    if not isinstance(obj, dict):
      raise argparse.ArgumentTypeError('must contain a JSON object, i.e. `{}`.')
    return obj

  helpstr='Run a recipe locally.'
  run_p = parser.add_parser(
    'run', help=helpstr, description=helpstr)

  run_p.add_argument(
    '--workdir',
    type=os.path.abspath,
    help='The working directory of recipe execution')
  run_p.add_argument(
    '--output-result-json',
    type=os.path.abspath,
    help=(
      'The file to write the JSON serialized returned value '
      ' of the recipe to'))
  run_p.add_argument(
    '--timestamps',
    action='store_true',
    help=(
      'If true, emit CURRENT_TIMESTAMP annotations. '
      'Default: false. '
      'CURRENT_TIMESTAMP annotation has one parameter, current time in '
      'Unix timestamp format. '
      'CURRENT_TIMESTAMP annotation will be printed at the beginning and '
      'end of the annotation stream and also immediately before each '
      'STEP_STARTED and STEP_CLOSED annotations.'))
  prop_group = run_p.add_mutually_exclusive_group()
  prop_group.add_argument(
    '--properties-file',
    dest='properties',
    type=properties_file_type,
    help=(
      'A file containing a json blob of properties. '
      'Pass "-" to read from stdin'))
  prop_group.add_argument(
    '--properties',
    type=properties_type,
    help='A json string containing the properties')

  run_p.add_argument(
    'recipe',
    help='The recipe to execute')
  run_p.add_argument(
    'props',
    nargs=argparse.REMAINDER,
    type=parse_prop,
    help=(
      'A list of property pairs; e.g. mastername=chromium.linux '
      'issue=12345. The property value will be decoded as JSON, but if '
      'this decoding fails the value will be interpreted as a string.'))

  run_p.set_defaults(properties={}, func=main)


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


def main(package_deps, args):
  from recipe_engine import step_runner
  from recipe_engine import stream

  config_file = args.package

  if args.props:
    for p in args.props:
      args.properties.update(p)

  properties = args.properties

  properties['recipe'] = args.recipe

  properties = util.strip_unicode(properties)

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'

  universe_view = loader.UniverseView(
      loader.RecipeUniverse(
          package_deps, config_file), package_deps.root_package)

  # TODO(iannucci): this is horrible; why do we want to set a workdir anyway?
  # Shouldn't the caller of recipes just CD somewhere if they want a different
  # workdir?
  workdir = (args.workdir or
      os.path.join(SCRIPT_PATH, os.path.pardir, 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  old_cwd = os.getcwd()
  os.chdir(workdir)

  op_args = args.operational_args

  stream_engine = stream.AnnotatorStreamEngine(
        sys.stdout,
        emit_timestamps=(args.timestamps or
                         op_args.annotation_flags.emit_timestamp))

  emit_initial_properties = op_args.annotation_flags.emit_initial_properties
  engine_flags = op_args.engine_flags

  # Have a top-level set of invariants to enforce StreamEngine expectations.
  with stream.StreamEngineInvariants.wrap(stream_engine) as stream_engine:
    try:
      ret = run_steps(
          properties, stream_engine,
          step_runner.SubprocessStepRunner(stream_engine, engine_flags),
          universe_view, engine_flags=engine_flags,
          emit_initial_properties=emit_initial_properties)
    finally:
      os.chdir(old_cwd)

    return handle_recipe_return(ret, args.output_result_json, stream_engine)
