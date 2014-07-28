#!/usr/bin/env python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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

TODO(vadimsh, iannucci): The following docs are very outdated.

Annotated_run.py will then import the recipe and expect to call a function whose
signature is:
  GenSteps(api, properties) -> iterable_of_things.

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

import copy
import functools
import json
import optparse
import os
import subprocess
import sys
import traceback

import cStringIO

import common.python26_polyfill  # pylint: disable=W0611
import collections  # Import after polyfill to get OrderedDict on 2.6

from common import annotator
from common import chromium_utils

from slave import recipe_loader
from slave import recipe_test_api
from slave import recipe_util


SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))


class StepPresentation(object):
  STATUSES = set(('SUCCESS', 'FAILURE', 'WARNING', 'EXCEPTION'))

  def __init__(self):
    self._finalized = False

    self._logs = collections.OrderedDict()
    self._links = collections.OrderedDict()
    self._perf_logs = collections.OrderedDict()
    self._status = None
    self._step_summary_text = ''
    self._step_text = ''
    self._properties = {}

  # (E0202) pylint bug: http://www.logilab.org/ticket/89092
  @property
  def status(self):  # pylint: disable=E0202
    return self._status

  @status.setter
  def status(self, val):  # pylint: disable=E0202
    assert not self._finalized
    assert val in self.STATUSES
    self._status = val

  @property
  def step_text(self):
    return self._step_text

  @step_text.setter
  def step_text(self, val):
    assert not self._finalized
    self._step_text = val

  @property
  def step_summary_text(self):
    return self._step_summary_text

  @step_summary_text.setter
  def step_summary_text(self, val):
    assert not self._finalized
    self._step_summary_text = val

  @property
  def logs(self):
    if not self._finalized:
      return self._logs
    else:
      return copy.deepcopy(self._logs)

  @property
  def links(self):
    if not self._finalized:
      return self._links
    else:
      return copy.deepcopy(self._links)

  @property
  def perf_logs(self):
    if not self._finalized:
      return self._perf_logs
    else:
      return copy.deepcopy(self._perf_logs)

  @property
  def properties(self):  # pylint: disable=E0202
    if not self._finalized:
      return self._properties
    else:
      return copy.deepcopy(self._properties)

  @properties.setter
  def properties(self, val):  # pylint: disable=E0202
    assert not self._finalized
    assert isinstance(val, dict)
    self._properties = val

  def finalize(self, annotator_step):
    self._finalized = True
    if self.step_text:
      annotator_step.step_text(self.step_text)
    if self.step_summary_text:
      annotator_step.step_summary_text(self.step_summary_text)
    for name, lines in self.logs.iteritems():
      annotator_step.write_log_lines(name, lines)
    for name, lines in self.perf_logs.iteritems():
      annotator_step.write_log_lines(name, lines, perf=True)
    for label, url in self.links.iteritems():
      annotator_step.step_link(label, url)
    status_mapping = {
      'WARNING': annotator_step.step_warnings,
      'FAILURE': annotator_step.step_failure,
      'EXCEPTION': annotator_step.step_exception,
    }
    status_mapping.get(self.status, lambda: None)()
    for key, value in self._properties.iteritems():
      annotator_step.set_build_property(key, json.dumps(value))


class StepData(object):
  def __init__(self, step, retcode):
    self._retcode = retcode
    self._step = step

    self._presentation = StepPresentation()
    self.abort_reason = None

  @property
  def step(self):
    return copy.deepcopy(self._step)

  @property
  def retcode(self):
    return self._retcode

  @property
  def presentation(self):
    return self._presentation

# Result of 'render_step', fed into 'step_callback'.
Placeholders = collections.namedtuple(
    'Placeholders', ['cmd', 'stdout', 'stderr', 'stdin'])


def render_step(step, step_test):
  """Renders a step so that it can be fed to annotator.py.

  Args:
    step_test: The test data json dictionary for this step, if any.
               Passed through unaltered to each placeholder.

  Returns any placeholder instances that were found while rendering the step.
  """
  # Process 'cmd', rendering placeholders there.
  placeholders = collections.defaultdict(lambda: collections.defaultdict(list))
  new_cmd = []
  for item in step.get('cmd', []):
    if isinstance(item, recipe_util.Placeholder):
      module_name, placeholder_name = item.name_pieces
      tdata = step_test.pop_placeholder(item.name_pieces)
      new_cmd.extend(item.render(tdata))
      placeholders[module_name][placeholder_name].append((item, tdata))
    else:
      new_cmd.append(item)
  step['cmd'] = new_cmd

  # Process 'stdout', 'stderr' and 'stdin' placeholders, if given.
  stdio_placeholders = {}
  for key in ('stdout', 'stderr', 'stdin'):
    placeholder = step.get(key)
    tdata = None
    if placeholder:
      assert isinstance(placeholder, recipe_util.Placeholder), key
      tdata = getattr(step_test, key)
      placeholder.render(tdata)
      assert placeholder.backing_file
      step[key] = placeholder.backing_file
    stdio_placeholders[key] = (placeholder, tdata)

  return Placeholders(cmd=placeholders, **stdio_placeholders)


def get_placeholder_results(step_result, placeholders):
  class BlankObject(object):
    pass

  # Placeholders inside step |cmd|.
  for module_name, pholders in placeholders.cmd.iteritems():
    assert not hasattr(step_result, module_name)
    o = BlankObject()
    setattr(step_result, module_name, o)

    for placeholder_name, items in pholders.iteritems():
      lst = [ph.result(step_result.presentation, td) for ph, td in items]
      setattr(o, placeholder_name+"_all", lst)
      setattr(o, placeholder_name, lst[0])

  # Placeholders that are used with IO redirection.
  for key in ('stdout', 'stderr', 'stdin'):
    assert not hasattr(step_result, key)
    ph, td = getattr(placeholders, key)
    result = ph.result(step_result.presentation, td) if ph else None
    setattr(step_result, key, result)


def get_callable_name(func):
  """Returns __name__ of a callable, handling functools.partial types."""
  if isinstance(func, functools.partial):
    return get_callable_name(func.func)
  else:
    return func.__name__


def step_callback(step, step_history, placeholders, step_test):
  assert step['name'] not in step_history, (
    'Step "%s" is already in step_history.' % step['name'])
  step_result = StepData(step, None)

  def _inner(annotator_step, retcode):
    step_result._retcode = retcode  # pylint: disable=W0212
    if retcode == 0:
      step_result.presentation.status = 'SUCCESS'
    else:
      step_result.presentation.status = 'FAILURE'

    annotator_step.annotation_stream.step_cursor(step['name'])
    if step_result.retcode != 0 and step_test.enabled:
      # To avoid cluttering the expectations, don't emit this in testmode.
      annotator_step.emit('step returned non-zero exit code: %d' %
                          step_result.retcode)

    get_placeholder_results(step_result, placeholders)

    return step_result

  return _inner

def get_args(argv):
  """Process command-line arguments."""

  parser = optparse.OptionParser(
      description='Entry point for annotated builds.')
  parser.add_option('--build-properties',
                    action='callback', callback=chromium_utils.convert_json,
                    type='string', default={},
                    help='build properties in JSON format')
  parser.add_option('--factory-properties',
                    action='callback', callback=chromium_utils.convert_json,
                    type='string', default={},
                    help='factory properties in JSON format')
  parser.add_option('--keep-stdin', action='store_true', default=False,
                    help='don\'t close stdin when running recipe steps')
  return parser.parse_args(argv)


def main(argv=None):
  opts, _ = get_args(argv)

  stream = annotator.StructuredAnnotationStream()

  ret = run_steps(stream, opts.build_properties, opts.factory_properties)
  return ret.status_code


# Return value of run_steps and RecipeEngine.run.
RecipeExecutionResult = collections.namedtuple(
    'RecipeExecutionResult', 'status_code steps_ran')


def run_steps(stream, build_properties, factory_properties,
              test_data=recipe_test_api.DisabledTestData()):
  """Returns a tuple of (status_code, steps_ran).

  Only one of these values will be set at a time. This is mainly to support the
  testing interface used by unittests/recipes_test.py.
  """
  stream.honor_zero_return_code()

  # TODO(iannucci): Stop this when blamelist becomes sane data.
  if ('blamelist_real' in build_properties and
      'blamelist' in build_properties):
    build_properties['blamelist'] = build_properties['blamelist_real']
    del build_properties['blamelist_real']

  properties = factory_properties.copy()
  properties.update(build_properties)

  # TODO(iannucci): A much better way to do this would be to dynamically
  #   detect if the mirrors are actually available during the execution of the
  #   recipe.
  if ('use_mirror' not in properties and (
    'TESTING_MASTERNAME' in os.environ or
    'TESTING_SLAVENAME' in os.environ)):
    properties['use_mirror'] = False

  # It's an integration point with a new recipe engine that can run steps
  # in parallel (that is not implemented yet). Use new engine only if explicitly
  # asked by setting 'engine' property to 'ParallelRecipeEngine'.
  engine = RecipeEngine.create(stream, properties, test_data)

  # Create all API modules and an instance of top level GenSteps generator.
  # It doesn't launch any recipe code yet (generator needs to be iterated upon
  # to start executing code).
  api = None
  with stream.step('setup_build') as s:
    assert 'recipe' in factory_properties
    recipe = factory_properties['recipe']

    run_recipe_line = (
        ['./scripts/tools/run_recipe.py', recipe] +
        ['%s=%r' % (prop, value) for prop, value in properties.iteritems()
         if prop not in ('recipe', 'use_mirror')]
    )
    lines = [
        'To repro this locally, run the following line from a build checkout:',
        '',
        subprocess.list2cmdline(run_recipe_line)
    ]
    for line in lines:
      s.step_log_line('run_recipe', line)
    s.step_log_end('run_recipe')

    try:
      recipe_module = recipe_loader.load_recipe(recipe)
      stream.emit('Running recipe with %s' % (properties,))
      api = recipe_loader.create_recipe_api(recipe_module.DEPS,
                                            engine,
                                            test_data)
      steps = recipe_module.GenSteps
      s.step_text('<br/>running recipe: "%s"' % recipe)
    except recipe_loader.NoSuchRecipe as e:
      s.step_text('<br/>recipe not found: %s' % e)
      s.step_failure()
      return RecipeExecutionResult(2, None)

  # Run the steps emitted by a recipe via the engine, emitting annotations
  # into |stream| along the way.
  return engine.run(steps, api)


class RecipeEngine(object):
  """Knows how to execute steps emitted by a recipe, holds global state such as
  step history and build properties. Each recipe module API has a reference to
  this object.

  Recipe modules that are aware of the engine:
    * properties - uses engine.properties.
    * step_history - uses engine.step_history.
    * step - uses engine.create_step(...).

  This class acts mostly as a documentation of expected public engine interface.
  """

  @staticmethod
  def create(stream, properties, test_data):
    """Create a new instance of RecipeEngine based on 'engine' property."""
    engine_cls_name = properties.get('engine', 'SequentialRecipeEngine')
    for cls in RecipeEngine.__subclasses__():
      if cls.__name__ == engine_cls_name:
        return cls(stream, properties, test_data)
    raise ValueError('Invalid engine class: %s' % (engine_cls_name,))

  @property
  def properties(self):
    """Global properties, merged --build_properties and --factory_properties."""
    raise NotImplementedError

  # TODO(martiniss) update documentation for this class
  def run(self, steps_function, api):
    """Run a recipe represented by top level GenSteps generator.

    This function blocks until recipe finishes.

    Args:
      generator: instance of GenSteps generator.

    Returns:
      RecipeExecutionResult with status code and list of steps ran.
    """
    raise NotImplementedError

  def unhandled_exception(self): # pylint: disable=R0201
    """Callback to handle unhandled exceptions.

    Must be called from an exceptional context. No arguments, but you can use
    sys.exc_info() to get information about the exception.

    Returns:
      RecipeExecutionResult with status code (recommended 4) and list of steps.
    """
    raise

  def create_step(self, step):
    """Called by step module to instantiate a new step. Return value of this
    function eventually surfaces as object yielded by GenSteps generator.

    Args:
      step: ConfigGroup object with information about the step, see
        recipe_modules/step/config.py.

    Returns:
      Opaque engine specific object that is understood by 'run_steps' method.
    """
    raise NotImplementedError


class SequentialRecipeEngine(RecipeEngine):
  """Always runs step sequentially. Currently the engine used by default."""
  def __init__(self, stream, properties, test_data):
    super(SequentialRecipeEngine, self).__init__()
    self._stream = stream
    self._properties = properties
    self._test_data = test_data
    self._step_history = collections.OrderedDict()

    self._previous_step_annotation = None
    self._previous_step_result = None
    self._api = None

  @property
  def properties(self):
    return self._properties

  def _emit_results(self):
    annotation = self._previous_step_annotation
    step_result = self._previous_step_result
    if not annotation or not step_result:
      return

    annotation.step_ended()
    step_result.presentation.finalize(annotation)
    if self._test_data.enabled:
      val = annotation.stream.getvalue()
      lines = filter(None, val.splitlines())
      if lines:
        # note that '~' sorts after 'z' so that this will be last on each
        # step. also use _step to get access to the mutable step
        # dictionary.
        # pylint: disable=w0212
        step_result._step['~followup_annotations'] = lines

  def run_step(self, step, ok_ret=None):
    test_data_fn = step.pop('step_test_data', recipe_test_api.StepTestData)
    step_test = self._test_data.pop_step_test_data(step['name'],
                                                   test_data_fn)
    placeholders = render_step(step, step_test)

    callback = step_callback(step, self._step_history,
                             placeholders, step_test)

    self._step_history[step['name']] = step
    self._emit_results()

    step_result = None

    if not self._test_data.enabled:
      self._previous_step_annotation, retcode = annotator.run_step(
        self._stream, **step)
      step_result = callback(self._previous_step_annotation, retcode)
    else:
      self._previous_step_annotation = annotation = self._stream.step(
              step['name'])
      annotation.step_started()
      try:
        annotation.stream = cStringIO.StringIO()
        step_result = callback(annotation, step_test.retcode)
      except OSError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        trace = traceback.format_exception(exc_type, exc_value, exc_tb)
        trace_lines = ''.join(trace).split('\n')
        annotation.write_log_lines('exception', filter(None, trace_lines))
        annotation.step_exception()

    self._previous_step_result = step_result
    if step_result.retcode != 0:
      raise self._api.StepFailure(step['name'], step_result)

    return step_result

  def run(self, steps_function, api):
    self._api = api
    try:
      build_result = steps_function(api)
      assert build_result is None, (
      "Non-None return from GenSteps is not supported yet")

      assert not self._test_data.enabled or not self._test_data.step_data, (
      "Unconsumed test data! %s" % (self._test_data.step_data,))
    except api.StepFailure as f:
      build_result = {
        "name": "$final_result",
        "reason": f.reason,
        "status_code": 1
      }
    except Exception:
      raise # TODO(martiniss) make this purple the build
    finally:
      self._emit_results()

    # TODO(martinis) clean up RecipeExecutionResult
    return RecipeExecutionResult(build_result, self._step_history)

  def unhandled_exception(self):
    (exc_type, exc_message) = sys.exc_info()[0:2]
    with self._stream.step('%s: %s' % (exc_type.__name__, exc_message)) as s:
      self._stream.emit('Exception: %s\nBacktrace:\n%s' %
                       (exc_message, traceback.format_exc(sys.exc_info()[2])))
      s.step_exception()
    raise

  def create_step(self, step):  # pylint: disable=R0201
    # This version of engine doesn't do anything, just converts step to dict
    # (that is consumed by annotator engine).
    return step.as_jsonish()


class ParallelRecipeEngine(RecipeEngine):
  """New engine that knows how to run steps in parallel.

  TODO(vadimsh): Implement it.
  """

  def __init__(self, stream, properties, test_data):
    super(ParallelRecipeEngine, self).__init__()
    self._stream = stream
    self._properties = properties
    self._test_data = test_data

  @property
  def properties(self):
    return self._properties

  def run(self, steps_function, api):
    raise NotImplementedError

  def create_step(self, step):
    raise NotImplementedError


def update_scripts():
  if os.environ.get('RUN_SLAVE_UPDATED_SCRIPTS'):
    os.environ.pop('RUN_SLAVE_UPDATED_SCRIPTS')
    return False

  stream = annotator.StructuredAnnotationStream()

  with stream.step('update_scripts') as s:
    build_root = os.path.join(SCRIPT_PATH, '..', '..')
    gclient_name = 'gclient'
    if sys.platform.startswith('win'):
      gclient_name += '.bat'
    gclient_path = os.path.join(build_root, '..', 'depot_tools', gclient_name)
    if subprocess.call([gclient_path, 'sync', '--force'], cwd=build_root) != 0:
      s.step_text('gclient sync failed!')
      s.step_warnings()
    os.environ['RUN_SLAVE_UPDATED_SCRIPTS'] = '1'

    # After running update scripts, set PYTHONIOENCODING=UTF-8 for the real
    # annotated_run.
    os.environ['PYTHONIOENCODING'] = 'UTF-8'

    return True


def shell_main(argv):
  if update_scripts():
    return subprocess.call([sys.executable] + argv)
  else:
    return main(argv)


if __name__ == '__main__':
  sys.exit(shell_main(sys.argv))
