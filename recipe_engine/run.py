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
  GetSteps(api, properties) -> iterable_of_things.

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
'keep_going' key on the steps which it has produced. Otherwise annoated_run will
cease calling the generator and move on to the next item in iterable_of_things.

'step_history' is an OrderedDict of {stepname -> StepData}, always representing
    the current history of what steps have run, what they returned, and any
    json data they emitted. Additionally, the OrderedDict has the following
    convenience functions defined:
      * last_step   - Returns the last step that ran or None
      * nth_step(n) - Returns the N'th step that ran or None

'failed' is a boolean representing if the build is in a 'failed' state.
"""

import copy
import inspect
import json
import optparse
import os
import subprocess
import sys

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


# Sentinel for marking all steps before for execution.
EXECUTE_NOW_SENTINEL = object()


def ensure_sequence_of_steps(step_or_steps):
  """Generates one or more fixed steps, given a step or a sequence of steps.
  Productions from generators are always followed by an EXECUTE_NOW_SENTINEL,
  so that the following steps are not seeded."""
  if isinstance(step_or_steps, dict):
    yield step_or_steps
  else:
    should_execute = inspect.isgenerator(step_or_steps)
    correct_type = (should_execute
                    or isinstance(step_or_steps, collections.Sequence))
    assert correct_type, ('Item is not a sequence or a step: %s'
                          % (step_or_steps,))
    for i in step_or_steps:
      for s in ensure_sequence_of_steps(i):
        yield s
      if should_execute:
        yield EXECUTE_NOW_SENTINEL


def seed_step_buffer(step_buffer):
  # Seed steps only if there is at least one more step after the current.
  if len(step_buffer) > 1:
    step_buffer[0]['seed_steps'] = [s['name'] for s in step_buffer]


def fixup_seed_steps(step_or_steps):
  step_buffer = []
  for step in ensure_sequence_of_steps(step_or_steps):
    if isinstance(step, dict):
      step_buffer.append(step)
    elif step is EXECUTE_NOW_SENTINEL:
      seed_step_buffer(step_buffer)
      for s in step_buffer:
        yield s
      step_buffer = []
    else:
      assert False, 'Item is not a step or sentinel: %s' % (step_or_steps,)
  seed_step_buffer(step_buffer)
  for s in step_buffer:
    yield s


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
  for item in step['cmd']:
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


def step_callback(step, step_history, placeholders, step_test):
  assert step['name'] not in step_history, (
    'Step "%s" is already in step_history!' % step['name'])
  step_result = StepData(step, None)
  step_history[step['name']] = step_result

  followup_fn = step.pop('followup_fn', None)

  def _inner(annotator_step, retcode):
    step_result._retcode = retcode  # pylint: disable=W0212
    if retcode > 0:
      step_result.presentation.status = 'FAILURE'

    annotator_step.annotation_stream.step_cursor(step['name'])
    if step_result.retcode != 0 and step_test.enabled:
      # To avoid cluttering the expectations, don't emit this in testmode.
      annotator_step.emit('step returned non-zero exit code: %d' %
                          step_result.retcode)

    get_placeholder_results(step_result, placeholders)

    try:
      if followup_fn:
        followup_fn(step_result)
    except recipe_util.RecipeAbort as e:
      step_result.abort_reason = str(e)

    step_result.presentation.finalize(annotator_step)
    return step_result
  if followup_fn:
    _inner.__name__ = followup_fn.__name__

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

  stream = annotator.StructuredAnnotationStream(seed_steps=['setup_build'])

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
  with stream.step('setup_build') as s:
    assert 'recipe' in factory_properties
    recipe = factory_properties['recipe']
    try:
      recipe_module = recipe_loader.load_recipe(recipe)
      stream.emit('Running recipe with %s' % (properties,))
      api = recipe_loader.create_recipe_api(recipe_module.DEPS,
                                            engine,
                                            test_data)
      steps = recipe_module.GenSteps(api)
      assert inspect.isgenerator(steps)
      s.step_text('<br/>running recipe: "%s"' % recipe)
    except recipe_loader.NoSuchRecipe as e:
      s.step_text('<br/>recipe not found: %s' % e)
      s.step_failure()
      return RecipeExecutionResult(2, None)

  # Run the steps emitted by a recipe via the engine, emitting annotations into
  # |stream| along the way.
  return engine.run(steps)


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

  @property
  def step_history(self):
    """OrderedDict objects with results of finished steps.

    Deprecated. New engine will provide future-like objects to wait for step
    results.
    """
    raise NotImplementedError

  def run(self, generator):
    """Run a recipe represented by top level GenSteps generator.

    This function blocks until recipe finishes.

    Args:
      generator: instance of GenSteps generator.

    Returns:
      RecipeExecutionResult with status code and list of steps ran.
    """
    raise NotImplementedError

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
    self._step_history.failed = False

  @property
  def step_history(self):
    return self._step_history

  @property
  def properties(self):
    return self._properties

  def run(self, generator):
    for step in fixup_seed_steps(generator):
      try:
        test_data_fn = step.pop('step_test_data', recipe_test_api.StepTestData)
        step_test = self._test_data.pop_step_test_data(step['name'],
                                                       test_data_fn)
        placeholders = render_step(step, step_test)

        if self._step_history.failed and not step.get('always_run', False):
          step['skip'] = True
          step.pop('followup_fn', None)
          step_result = StepData(step, None)
          self._step_history[step['name']] = step_result
          continue

        callback = step_callback(step, self._step_history,
                                 placeholders, step_test)

        if not self._test_data.enabled:
          step_result = annotator.run_step(
            self._stream, followup_fn=callback, **step)
        else:
          with self._stream.step(step['name']) as s:
            s.stream = cStringIO.StringIO()
            step_result = callback(s, step_test.retcode)
            lines = filter(None, s.stream.getvalue().splitlines())
            if lines:
              # Note that '~' sorts after 'z' so that this will be last on each
              # step. Also use _step to get access to the mutable step
              # dictionary.
              # pylint: disable=W0212
              step_result._step['~followup_annotations'] = lines

        if step_result.abort_reason:
          self._stream.emit('Aborted: %s' % step_result.abort_reason)
          if self._test_data.enabled:
            self._test_data.step_data.clear()  # Dump the rest of the test data
          self._step_history.failed = True
          break

        # TODO(iannucci): Pull this failure calculation into callback.
        self._step_history.failed = annotator.update_build_failure(
            self._step_history.failed,
            step_result.retcode,
            **step)
      except Exception as e:
        new_message = (
          '%s\n'
          '  while processing step `%s`:\n'
          '  %s'
        ) % (e.message, step['name'], json.dumps(step, indent=2, sort_keys=True,
                                                 default=str))
        raise type(e), type(e)(new_message), sys.exc_info()[2]

    assert not self._test_data.enabled or not self._test_data.step_data, (
      "Unconsumed test data! %s" % (self._test_data.step_data,))

    return RecipeExecutionResult(0 if not self._step_history.failed else 1,
                                 self._step_history)

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

  @property
  def step_history(self):
    raise NotImplementedError

  def run(self, generator):
    raise NotImplementedError

  def create_step(self, step):
    raise NotImplementedError


def update_scripts():
  if os.environ.get('RUN_SLAVE_UPDATED_SCRIPTS'):
    os.environ.pop('RUN_SLAVE_UPDATED_SCRIPTS')
    return False
  stream = annotator.StructuredAnnotationStream(seed_steps=['update_scripts'])
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
    return True


def shell_main(argv):
  if update_scripts():
    return subprocess.call([sys.executable] + argv)
  else:
    return main(argv)


if __name__ == '__main__':
  sys.exit(shell_main(sys.argv))
