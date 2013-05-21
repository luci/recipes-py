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

Annotated_run.py will then import the recipe and expect to call a function whose
signature is:
  GetSteps(api, factory_properties, build_properties) -> iterable_of_things.

Items in iterable_of_things must be one of:
  * A step dictionary (as accepted by annotator.py)
  * A sequence of step dictionaries
  * A step generator

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

import collections
import contextlib
import json
import optparse
import os
import subprocess
import sys
import tempfile

from collections import namedtuple, OrderedDict
from itertools import islice

from common import annotator
from common import chromium_utils
from slave import recipe_util

SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))
BUILD_ROOT = os.path.dirname(os.path.dirname(SCRIPT_PATH))


@contextlib.contextmanager
def temp_purge_path(path):
  saved = sys.path
  sys.path = [path]
  try:
    yield
  finally:
    sys.path = saved


class StepData(object):
  __slots__ = ['step', 'retcode', 'json_data']
  def __init__(self, step=None, retcode=None, json_data=None):
    self.step      = step
    self.retcode   = retcode
    self.json_data = json_data


def expand_root_placeholder(root, lst):
  """This expands CheckoutRootPlaceholder in paths to a real path.
  See recipe_util.checkout_path() for usage."""
  ret = []
  replacements = {'CheckoutRootPlaceholder': root}
  for item in lst:
    if isinstance(item, basestring):
      if '%(CheckoutRootPlaceholder)s' in item:
        assert root, 'Must use "checkout" key to use checkout_path().'
        ret.append(item % replacements)
        continue
    ret.append(item)
  return ret


def fixup_seed_steps(sequence):
  """Takes a sequence of step dict's and adds seed_steps to the first entry
  if appropriate."""
  if sequence and 'seed_steps' not in sequence[0]:
    sequence[0]['seed_steps'] = [x['name'] for x in sequence]


def ensure_sequence_of_steps(step_or_steps):
  """Generates one or more fixed steps, given a step or a sequence of steps."""
  if isinstance(step_or_steps, collections.Sequence):
    step_seq = step_or_steps
    fixup_seed_steps(step_seq)
    for s in step_seq:
      yield s
  else:
    yield step_or_steps


def step_generator_wrapper(steps, step_history, is_failed):
  """Generates single steps from the non-homogeneous sequence 'steps'.

  Each item in steps may be:
    * A step (dict)
    * A sequence of steps
    * A generator of:
      * A step
      * A sequence of steps
  """
  for thing in steps:
    if isinstance(thing, (collections.Sequence, dict)):
      for step in ensure_sequence_of_steps(thing):
        yield step
    else:
      # step generator
      step_iter = thing(step_history, is_failed())
      first = True
      try:
        while True:
          # Cannot pass non-None to first generator call.
          step_or_steps = step_iter.send(is_failed() if not first else None)
          first = False

          for step in ensure_sequence_of_steps(step_or_steps):
            keep_going = step.pop('keep_going', False)
            yield step
            if is_failed() and not keep_going:
              raise StopIteration
      except StopIteration:
        pass


def create_step_history():
  """Returns an OrderedDict with some helper functions attached."""
  step_history = OrderedDict()

  # Add in some helpers.
  def last_step():
    """Returns the last item from step_history, or None."""
    key = next(reversed(step_history), None)
    return step_history[key] if key else None
  step_history.last_step = last_step

  def nth_step(n):
    """Returns the N'th step from step_history, or None."""
    return next(islice(step_history.iteritems(), n, None), None)
  step_history.nth_step = nth_step
  return step_history


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


def run_steps(stream, build_properties, factory_properties, test_data=None):
  """Returns a tuple of (status_code, steps_ran).

  Only one of these values will be set at a time. This is mainly to support the
  testing interface used by unittests/recipes_test.py.

  test_data should be a dictionary of step_name -> (retcode, json_data)
  """
  MakeStepsRetval = namedtuple('MakeStepsRetval', 'status_code steps_ran')

  # TODO(iannucci): Stop this when blamelist becomes sane data.
  if ('blamelist_real' in build_properties and
      'blamelist' in build_properties):
    build_properties['blamelist'] = build_properties['blamelist_real']
    del build_properties['blamelist_real']

  with stream.step('setup_build') as s:
    assert 'recipe' in factory_properties
    recipe = factory_properties['recipe']
    recipe_dirs = (os.path.abspath(p) for p in (
        os.path.join(SCRIPT_PATH, '..', '..', '..', 'build_internal', 'scripts',
                     'slave-internal', 'recipes'),
        os.path.join(SCRIPT_PATH, '..', '..', '..', 'build_internal', 'scripts',
                     'slave', 'recipes'),
        os.path.join(SCRIPT_PATH, 'recipes'),
    ))

    for path in recipe_dirs:
      recipe_module = None
      with temp_purge_path(path):
        try:
          recipe_module = __import__(recipe, globals(), locals())
        except ImportError:
          continue
      steps = recipe_module.GetSteps(
          recipe_util,
          factory_properties.copy(),
          build_properties.copy())
      assert isinstance(steps, (list, tuple))
      break
    else:
      s.step_text('recipe not found')
      s.step_failure()
      return MakeStepsRetval(1, None)

  # Execute annotator.py with steps if specified.
  # annotator.py handles the seeding, execution, and annotation of each step.
  factory_properties_str = json.dumps(factory_properties)
  build_properties_str = json.dumps(build_properties)
  property_placeholder_lst = [
      '--factory-properties', factory_properties_str,
      '--build-properties', build_properties_str]

  failed = False
  step_history = create_step_history()

  root = None
  for step in step_generator_wrapper(steps, step_history, lambda: failed):
    json_output_fd = json_output_name = None
    new_cmd = []
    for item in expand_root_placeholder(root, step['cmd']):
      if item == recipe_util.PropertyPlaceholder:
        new_cmd.extend(property_placeholder_lst)
      elif item == recipe_util.JsonOutputPlaceholder:
        new_cmd.append('--output-json')
        if test_data:
          new_cmd.append('/path/to/tmp/json')
        else:
          assert json_output_fd is None, (
            'Can only use json_output_file once per step' % step)
          json_output_fd, json_output_name = tempfile.mkstemp()
          new_cmd.append(json_output_name)
      else:
        new_cmd.append(item)
    step['cmd'] = new_cmd
    if 'cwd' in step:
      [new_cwd] = expand_root_placeholder(root, [step['cwd']])
      step['cwd'] = new_cwd

    json_data = step.pop('static_json_data', {})
    assert not(json_data and json_output_fd), (
      "Cannot have both static_json_data as well as dynamic json_data")
    if test_data is None:
      failed, retcode = annotator.run_step(stream, failed, **step)
      if json_output_fd is not None:
        try:
          json_data = json.load(os.fdopen(json_output_fd, 'r'))
          print 'step returned json data: %s' % json_data
        except ValueError:
          pass
    else:
      retcode, potential_json_data = test_data.pop(step['name'], (0, {}))
      json_data = json_data or potential_json_data
      failed = failed or retcode != 0

    # Support CheckoutRootPlaceholder.
    root = root or json_data.get('CheckoutRoot', None)

    assert step['name'] not in step_history
    step_history[step['name']] = StepData(step, retcode, json_data)

  assert test_data is None or test_data == {}, (
    "Unconsumed test data! %s" % (test_data,))

  return MakeStepsRetval(retcode, step_history)


def UpdateScripts():
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


if __name__ == '__main__':
  if UpdateScripts():
    os.execv(sys.executable, [sys.executable] + sys.argv)
  sys.exit(main(sys.argv))
