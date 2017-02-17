# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Entry point for fully-annotated builds.

This script is part of the effort to move all builds to annotator-based
systems. Any builder configured to use the AnnotatorFactory.BaseFactory()
found in scripts/master/factory/annotator_factory.py executes a single
AddAnnotatedScript step. That step (found in annotator_commands.py) calls
this script with the build- and factory-properties passed on the command
line.

The main mode of operation is for factory_properties to contain a single
property 'recipe' whose value is the basename (without extension) of a python
script in one of the following locations (looked up in this order):
  * build_internal/scripts/slave-internal/recipes
  * build_internal/scripts/slave/recipes
  * build/scripts/slave/recipes

For example, these factory_properties would run the 'run_presubmit' recipe
located in build/scripts/slave/recipes:
    { 'recipe': 'run_presubmit' }

TODO(vadimsh, iannucci, luqui): The following docs are very outdated.

Annotated_run.py will then import the recipe and expect to call a function whose
signature is:
  RunSteps(api, properties) -> None.

properties is a merged view of factory_properties with build_properties.

Items in iterable_of_things must be one of:
  * A step dictionary (as accepted by annotator.py)
  * A sequence of step dictionaries
  * A step generator
Iterable_of_things is also permitted to be a raw step generator.

A step generator is called with the following protocol:
  * The generator is initialized with 'step_history' and 'failed'.
  * Each iteration of the generator is passed the current value of 'failed'.

On each iteration, a step generator may yield:
  * A single step dictionary
  * A sequence of step dictionaries
    * If a sequence of dictionaries is yielded, and the first step dictionary
      does not have a 'seed_steps' key, the first step will be augmented with
      a 'seed_steps' key containing the names of all the steps in the sequence.

For steps yielded by the generator, if annotated_run enters the failed state,
it will only continue to call the generator if the generator sets the
'keep_going' key on the steps which it has produced. Otherwise annotated_run
will cease calling the generator and move on to the next item in
iterable_of_things.

'step_history' is an OrderedDict of {stepname -> StepData}, always representing
    the current history of what steps have run, what they returned, and any
    json data they emitted. Additionally, the OrderedDict has the following
    convenience functions defined:
      * last_step   - Returns the last step that ran or None
      * nth_step(n) - Returns the N'th step that ran or None

'failed' is a boolean representing if the build is in a 'failed' state.
"""

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
from . import result_pb2
import subprocess42


SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))

BUILDBOT_MAGIC_ENV = set([
    'BUILDBOT_BLAMELIST',
    'BUILDBOT_BRANCH',
    'BUILDBOT_BUILDBOTURL',
    'BUILDBOT_BUILDERNAME',
    'BUILDBOT_BUILDNUMBER',
    'BUILDBOT_CLOBBER',
    'BUILDBOT_GOT_REVISION',
    'BUILDBOT_MASTERNAME',
    'BUILDBOT_REVISION',
    'BUILDBOT_SCHEDULER',
    'BUILDBOT_SLAVENAME',
])

ENV_WHITELIST_PYTHON = set([
    'PYTHONPATH',
    'PYTHONUNBUFFERED',
])

ENV_WHITELIST_SWARMING = set([
    'SWARMING_BOT_ID',
    'SWARMING_HEADLESS',
    'SWARMING_TASK_ID',
])

ENV_WHITELIST_LOGDOG = set([
    'LOGDOG_STREAM_SERVER_PATH',
    'LOGDOG_STREAM_PROJECT',
    'LOGDOG_STREAM_PREFIX',
    'LOGDOG_COORDINATOR_HOST',
])

ENV_WHITELIST_CIPD = set([
    'CIPD_CACHE_DIR',
])

ENV_WHITELIST_INFRA = (ENV_WHITELIST_PYTHON | ENV_WHITELIST_SWARMING |
                       ENV_WHITELIST_LOGDOG | ENV_WHITELIST_CIPD | set([
    'AWS_CREDENTIAL_FILE',
    'BOTO_CONFIG',
    'BUILDBOT_ARCHIVE_FORCE_SSH',
    'CHROME_HEADLESS',
    'CHROMIUM_BUILD',
    'GIT_USER_AGENT',
    'TESTING_MASTER',
    'TESTING_MASTER_HOST',
    'TESTING_SLAVENAME',
]))

ENV_WHITELIST_WIN = ENV_WHITELIST_INFRA | BUILDBOT_MAGIC_ENV | set([
    # infra windows specific
    'DEPOT_TOOLS_GIT_BLEEDING',

    'APPDATA',
    'COMMONPROGRAMFILES',
    'COMMONPROGRAMFILES(X86)',
    'COMMONPROGRAMW6432',
    'COMSPEC',
    'COMPUTERNAME',
    'DBUS_SESSION_BUS_ADDRESS',
    'DXSDK_DIR',
    'HOME',
    'HOMEDRIVE',
    'HOMEPATH',
    'LOCALAPPDATA',
    'NUMBER_OF_PROCESSORS',
    'OS',
    'PATH',
    'PATHEXT',
    'PROCESSOR_ARCHITECTURE',
    'PROCESSOR_ARCHITEW6432',
    'PROCESSOR_IDENTIFIER',
    'PROGRAMFILES',
    'PROGRAMW6432',
    'PWD',
    'SYSTEMDRIVE',
    'SYSTEMROOT',
    'TEMP',
    'TMP',
    'USERNAME',
    'USERDOMAIN',
    'USERPROFILE',
    'VS100COMNTOOLS',
    'VS110COMNTOOLS',
    'WINDIR',
])

ENV_WHITELIST_POSIX = ENV_WHITELIST_INFRA | BUILDBOT_MAGIC_ENV | set([
    # infra posix specific
    'CHROME_ALLOCATOR',
    'CHROME_VALGRIND_NUMCPUS',

    'CCACHE_DIR',
    'DISPLAY',
    'DISTCC_DIR',
    'HOME',
    'HOSTNAME',
    'HTTP_PROXY',
    'http_proxy',
    'HTTPS_PROXY',
    'LANG',
    'LOGNAME',
    'PAGER',
    'PATH',
    'PWD',
    'SHELL',
    'SSH_AGENT_PID',
    'SSH_AUTH_SOCK',
    'SSH_CLIENT',
    'SSH_CONNECTION',
    'SSH_TTY',
    'USER',
    'USERNAME',
])

# TODO(martiniss): Remove this
RecipeResult = collections.namedtuple('RecipeResult', 'result')

# TODO(dnj): Replace "properties" with a generic runtime instance. This instance
# will be used to seed recipe clients and expanded to include managed runtime
# entities.
def run_steps(properties, stream_engine, step_runner, universe_view,
              engine_flags=None, emit_initial_properties=False):
  """Runs a recipe (given by the 'recipe' property).

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

    engine = RecipeEngine(step_runner, properties, universe_view, engine_flags)

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
        '%s' % json.dumps(properties),
        'EOF',
        '',
        'To run on Windows, you can put the JSON in a file and redirect the',
        'contents of the file into run_recipe.py, with the < operator.',
    ]

    with s.new_log_stream('run_recipe') as l:
      for line in run_recipe_help_lines:
        l.write_line(line)

    _isolate_environment()

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
      if engine_flags and engine_flags.use_result_proto:
        return result_pb2.Result(
            failure=result_pb2.Failure(
                human_reason=str(e),
                exception=result_pb2.Exception(
                  traceback=traceback.format_exc().splitlines()
                )))
      return RecipeResult({
          'status_code': 2,
          'reason': str(e),
      })

  # Run the steps emitted by a recipe via the engine, emitting annotations
  # into |stream| along the way.
  return engine.run(recipe_script, api, properties)


def _isolate_environment():
  """Isolate the environment to a known subset set."""
  if sys.platform.startswith('win'):
    whitelist = ENV_WHITELIST_WIN
  elif sys.platform in ('darwin', 'posix', 'linux2'):
    whitelist = ENV_WHITELIST_POSIX
  else:
    print ('WARNING: unknown platform %s, not isolating environment.' %
           sys.platform)
    return

  for k in os.environ.keys():
    if k not in whitelist:
      del os.environ[k]


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

  def __init__(self, step_runner, properties, universe_view, engine_flags=None):
    """See run_steps() for parameter meanings."""
    self._step_runner = step_runner
    self._properties = properties
    self._universe_view = universe_view
    self._clients = {client.IDENT: client for client in (
        recipe_api.PathsClient(),
        recipe_api.StepClient(self),
        recipe_api.PropertiesClient(self),
        recipe_api.DependencyManagerClient(self),
    )}
    self._engine_flags = engine_flags

    # A stack of ActiveStep objects, holding the most recently executed step at
    # each nest level (objects deeper in the stack have lower nest levels).
    # When we pop from this stack, we close the corresponding step stream.
    self._step_stack = []

    # TODO(iannucci): come up with a more structured way to advertise/set mode
    # flags/options for the engine.
    if '$recipe_engine' in properties:
      options = properties['$recipe_engine']
      try:
        mode_flags = options.get('mode_flags')
        if mode_flags:
          if mode_flags.get('use_subprocess42'):
            print "IGNORING MODE_SUBPROCESS42"
      except Exception as e:
        print "Failed to set recipe_engine options, got: %r: %s" % (options, e)

  @property
  def properties(self):
    return self._properties

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
      step_config (recipe_api.StepConfig): The step configuration to run.

    Returns:
      A StepData object containing the result of running the step.
    """
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

      if step_result.retcode in step_config.ok_ret:
        step_result.presentation.status = 'SUCCESS'
        return step_result
      else:
        if not step_config.infra_step:
          state = 'FAILURE'
          exc = recipe_api.StepFailure
        else:
          state = 'EXCEPTION'
          exc = recipe_api.InfraFailure

        step_result.presentation.status = state

        self._step_stack[-1].open_step.stream.write_line(
            'step returned non-zero exit code: %d' % step_result.retcode)

        raise exc(step_config.name, step_result)

  def run(self, recipe_script, api, properties):
    """Run a recipe represented by a recipe_script object.

    This function blocks until recipe finishes.
    It mainly executes the recipe, and has some exception handling logic.

    Args:
      recipe_script: The recipe to run, as represented by a RecipeScript object.
      api: The api, with loaded module dependencies.
           Used by the some special modules.
      properties: a dictionary of properties to pass to the recipe.

    Returns:
      result_pb2.Result which has return value or status code and exception.
        or
      RecipeResult which has return value or status code and exception.
        depending on the value of self._engine_flags.use_result_proto
    """
    self._get_client('paths')._initialize_with_recipe_api(api)

    # TODO(martiniss): Remove this once we've transitioned to the new results
    # format
    if self._engine_flags and self._engine_flags.use_result_proto:
      logging.info("Using new result proto logic")
      return self._new_run(recipe_script, api, properties)
    return self._old_run(recipe_script, api, properties)

  def _new_run(self, recipe_script, api, properties):
    result = None

    with self._step_runner.run_context():
      try:
        try:
          recipe_result = recipe_script.run(api, properties)
          result = result_pb2.Result(json_result=json.dumps(recipe_result))
        finally:
          self._close_through_level(0)
      except recipe_api.StepFailure as f:
        result = result_pb2.Result(
          failure=result_pb2.Failure(
              human_reason=f.reason,
              failure=result_pb2.StepFailure(
                  step=f.name
              )))

      except types.StepDataAttributeError as ex:
        result = result_pb2.Result(
            failure=result_pb2.Failure(
                human_reason=ex.message,
                step_data=result_pb2.StepData(
                    step=f.name
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

  def _old_run(self, recipe_script, api, properties):
    with self._step_runner.run_context():
      try:
        try:
          recipe_result = recipe_script.run(api, properties)
          result = {
            "recipe_result": recipe_result,
            "status_code": 0
          }
        finally:
          self._close_through_level(0)
      except recipe_api.StepFailure as f:
        result = {
          # Include "recipe_result" so it doesn't get marked as infra failure.
          "recipe_result": None,
          "reason": f.reason,
          "status_code": f.retcode or 1
        }
      except types.StepDataAttributeError as ex:
        result = {
          "reason": "Invalid Step Data Access: %r" % ex,
          "traceback": traceback.format_exc().splitlines(),
          "status_code": -1
        }

        raise
      except subprocess42.TimeoutExpired as ex:
        result = {
          "reason": "Step time out: %r" % ex,
          "traceback": traceback.format_exc().splitlines(),
          "status_code": -1
        }
      except Exception as ex:
        result = {
          "reason": "Uncaught Exception: %r" % ex,
          "traceback": traceback.format_exc().splitlines(),
          "status_code": -1
        }

        raise

    result['name'] = '$result'
    return RecipeResult(result)

  def depend_on(self, recipe, properties, distributor=None):
    return self.depend_on_multi(
        ((recipe, properties),), distributor=distributor)[0]

  def depend_on_multi(self, dependencies, distributor=None):
    results = []
    for recipe, properties in dependencies:
      recipe_script = self._universe_view.load_recipe(recipe, engine=self)

      if not recipe_script.RETURN_SCHEMA:
        raise ValueError(
            "Invalid recipe %s. Recipe must have a return schema." % recipe)

      # run_recipe is a function which will be called once the properties have
      # been validated by the recipe engine. The arguments being passed in are
      # simply the values being passed to the recipe, which we already know, so
      # we ignore them. We're only using this for its properties validation
      # functionality.
      run_recipe = lambda *args, **kwargs: (
        self._step_runner.run_recipe(self._universe_view, recipe, properties))

      try:
        # This does type checking for properties
        results.append(
          loader._invoke_with_properties(
            run_recipe, properties, recipe_script.PROPERTIES,
            properties.keys()))
      except TypeError as e:
        raise TypeError(
            "Got %r while trying to call recipe %s with properties %r" % (
              e, recipe, properties))

    return results
