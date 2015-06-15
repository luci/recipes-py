# Copyright (c) 2013-2015 The Chromium Authors. All rights reserved.
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

import collections
import contextlib
import copy
import functools
import json
import os
import subprocess
import sys
import threading
import traceback

import cStringIO


from . import loader
from . import recipe_api
from . import recipe_test_api
from . import util


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
      annotator_step.set_build_property(key, json.dumps(value, sort_keys=True))


class StepDataAttributeError(AttributeError):
  """Raised when a non-existent attributed is accessed on a StepData object."""
  def __init__(self, step, attr):
    self.step = step
    self.attr = attr
    message = ('The recipe attempted to access missing step data "%s" for step '
               '"%s". Please examine that step for errors.' % (attr, step))
    super(StepDataAttributeError, self).__init__(message)


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

  def __getattr__(self, name):
    raise StepDataAttributeError(self._step['name'], name)


# TODO(martiniss) update comment
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
    if isinstance(item, util.Placeholder):
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
      assert isinstance(placeholder, util.Placeholder), key
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


# Return value of run_steps and RecipeEngine.run.
RecipeExecutionResult = collections.namedtuple(
    'RecipeExecutionResult', 'status_code steps_ran')


def run_steps(properties,
              stream,
              universe,
              test_data=recipe_test_api.DisabledTestData()):
  """Returns a tuple of (status_code, steps_ran).

  Only one of these values will be set at a time. This is mainly to support the
  testing interface used by unittests/recipes_test.py.
  """
  stream.honor_zero_return_code()

  # TODO(iannucci): Stop this when blamelist becomes sane data.
  if ('blamelist_real' in properties and
      'blamelist' in properties):
    properties['blamelist'] = properties['blamelist_real']
    del properties['blamelist_real']

  # NOTE(iannucci): 'root' was a terribly bad idea and has been replaced by
  # 'patch_project'. 'root' had Rietveld knowing about the implementation of
  # the builders. 'patch_project' lets the builder (recipe) decide its own
  # destiny.
  properties.pop('root', None)

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
    assert 'recipe' in properties # Should be ensured by get_recipe_properties.
    recipe = properties['recipe']

    properties_to_print = properties.copy()
    if 'use_mirror' in properties:
      del properties_to_print['use_mirror']

    run_recipe_help_lines = [
        'To repro this locally, run the following line from a build checkout:',
        '',
        './scripts/tools/run_recipe.py %s --properties-file - <<EOF' % recipe,
        repr(properties_to_print),
        'EOF',
        '',
        'To run on Windows, you can put the JSON in a file and redirect the',
        'contents of the file into run_recipe.py, with the < operator.',
    ]

    for line in run_recipe_help_lines:
      s.step_log_line('run_recipe', line)
    s.step_log_end('run_recipe')

    try:
      recipe_module = universe.load_recipe(recipe)
      stream.emit('Running recipe with %s' % (properties,))
      api = loader.create_recipe_api(recipe_module.LOADED_DEPS,
                                            engine,
                                            test_data)
      steps = recipe_module.GenSteps
      s.step_text('<br/>running recipe: "%s"' % recipe)
    except loader.NoSuchRecipe as e:
      s.step_text('<br/>recipe not found: %s' % e)
      s.step_failure()
      return RecipeExecutionResult(2, None)

  # Run the steps emitted by a recipe via the engine, emitting annotations
  # into |stream| along the way.
  return engine.run(steps, api)


def _merge_envs(original, override):
  """Merges two environments.

  Returns a new environment dict with entries from |override| overwriting
  corresponding entries in |original|. Keys whose value is None will completely
  remove the environment variable. Values can contain %(KEY)s strings, which
  will be substituted with the values from the original (useful for amending, as
  opposed to overwriting, variables like PATH).
  """
  result = original.copy()
  if not override:
    return result
  for k, v in override.items():
    if v is None:
      if k in result:
        del result[k]
    else:
      result[str(k)] = str(v) % original
  return result


def _print_step(step, env, stream):
  """Prints the step command and relevant metadata.

  Intended to be similar to the information that Buildbot prints at the
  beginning of each non-annotator step.
  """
  step_info_lines = []
  step_info_lines.append(' '.join(step['cmd']))
  step_info_lines.append('in dir %s:' % (step['cwd'] or os.getcwd()))
  for key, value in sorted(step.items()):
    if value is not None:
      if callable(value):
        # This prevents functions from showing up as:
        #   '<function foo at 0x7f523ec7a410>'
        # which is tricky to test.
        value = value.__name__+'(...)'
      step_info_lines.append(' %s: %s' % (key, value))
  step_info_lines.append('full environment:')
  for key, value in sorted(env.items()):
    step_info_lines.append(' %s: %s' % (key, value))
  step_info_lines.append('')
  stream.emit('\n'.join(step_info_lines))


@contextlib.contextmanager
def _modify_lookup_path(path):
  """Places the specified path into os.environ.

  Necessary because subprocess.Popen uses os.environ to perform lookup on the
  supplied command, and only uses the |env| kwarg for modifying the environment
  of the child process.
  """
  saved_path = os.environ['PATH']
  try:
    if path is not None:
      os.environ['PATH'] = path
    yield
  finally:
    os.environ['PATH'] = saved_path


def _normalize_change(change):
  assert isinstance(change, dict), 'Change is not a dict'
  change = change.copy()

  # Convert when_timestamp to UNIX timestamp.
  when = change.get('when_timestamp')
  if isinstance(when, datetime.datetime):
    when = calendar.timegm(when.utctimetuple())
    change['when_timestamp'] = when

  return change


def _trigger_builds(step, trigger_specs):
  assert trigger_specs is not None
  for trig in trigger_specs:
    builder_name = trig.get('builder_name')
    if not builder_name:
      raise ValueError('Trigger spec: builder_name is not set')

    changes = trig.get('buildbot_changes', [])
    assert isinstance(changes, list), 'buildbot_changes must be a list'
    changes = map(_normalize_change, changes)

    step.step_trigger(json.dumps({
        'builderNames': [builder_name],
        'bucket': trig.get('bucket'),
        'changes': changes,
        'properties': trig.get('properties'),
    }, sort_keys=True))


def _run_annotated_step(
    stream, name, cmd, cwd=None, env=None, allow_subannotations=False,
    trigger_specs=None, nest_level=0, **kwargs):
  """Runs a single step.

  Context:
    stream: StructuredAnnotationStream to use to emit step

  Step parameters:
    name: name of the step, will appear in buildbots waterfall
    cmd: command to run, list of one or more strings
    cwd: absolute path to working directory for the command
    env: dict with overrides for environment variables
    allow_subannotations: if True, lets the step emit its own annotations
    trigger_specs: a list of trigger specifications, which are dict with keys:
        properties: a dict of properties.
            Buildbot requires buildername property.

  Known kwargs:
    stdout: Path to a file to put step stdout into. If used, stdout won't appear
            in annotator's stdout (and |allow_subannotations| is ignored).
    stderr: Path to a file to put step stderr into. If used, stderr won't appear
            in annotator's stderr.
    stdin: Path to a file to read step stdin from.

  Returns the returncode of the step.
  """
  if isinstance(cmd, basestring):
    cmd = (cmd,)
  cmd = map(str, cmd)

  # For error reporting.
  step_dict = kwargs.copy()
  step_dict.update({
      'name': name,
      'cmd': cmd,
      'cwd': cwd,
      'env': env,
      'allow_subannotations': allow_subannotations,
      })
  step_env = _merge_envs(os.environ, env)

  step_annotation = stream.step(name)
  step_annotation.step_started()

  if nest_level:
    step_annotation.step_nest_level(nest_level)

  _print_step(step_dict, step_env, stream)
  returncode = 0
  if cmd:
    try:
      # Open file handles for IO redirection based on file names in step_dict.
      fhandles = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'stdin': None,
      }
      for key in fhandles:
        if key in step_dict:
          fhandles[key] = open(step_dict[key],
                               'rb' if key == 'stdin' else 'wb')

      if sys.platform.startswith('win'):
        # Windows has a bad habit of opening a dialog when a console program
        # crashes, rather than just letting it crash.  Therefore, when a program
        # crashes on Windows, we don't find out until the build step times out.
        # This code prevents the dialog from appearing, so that we find out
        # immediately and don't waste time waiting for a user to close the
        # dialog.
        import ctypes
        # SetErrorMode(SEM_NOGPFAULTERRORBOX). For more information, see:
        # https://msdn.microsoft.com/en-us/library/windows/desktop/ms680621.aspx
        ctypes.windll.kernel32.SetErrorMode(0x0002)
        # CREATE_NO_WINDOW. For more information, see:
        # https://msdn.microsoft.com/en-us/library/windows/desktop/ms684863.aspx
        creationflags = 0x8000000
      else:
        creationflags = 0

      with _modify_lookup_path(step_env.get('PATH')):
        proc = subprocess.Popen(
            cmd,
            env=step_env,
            cwd=cwd,
            universal_newlines=True,
            creationflags=creationflags,
            **fhandles)

      # Safe to close file handles now that subprocess has inherited them.
      for handle in fhandles.itervalues():
        if isinstance(handle, file):
          handle.close()

      outlock = threading.Lock()
      def filter_lines(lock, allow_subannotations, inhandle, outhandle):
        while True:
          line = inhandle.readline()
          if not line:
            break
          lock.acquire()
          try:
            if not allow_subannotations and line.startswith('@@@'):
              outhandle.write('!')
            outhandle.write(line)
            outhandle.flush()
          finally:
            lock.release()

      # Pump piped stdio through filter_lines. IO going to files on disk is
      # not filtered.
      threads = []
      for key in ('stdout', 'stderr'):
        if fhandles[key] == subprocess.PIPE:
          inhandle = getattr(proc, key)
          outhandle = getattr(sys, key)
          threads.append(threading.Thread(
              target=filter_lines,
              args=(outlock, allow_subannotations, inhandle, outhandle)))

      for th in threads:
        th.start()
      proc.wait()
      for th in threads:
        th.join()
      returncode = proc.returncode
    except OSError:
      # File wasn't found, error will be reported to stream when the exception
      # crosses the context manager.
      step_annotation.step_exception_occured(*sys.exc_info())
      raise

  # TODO(martiniss) move logic into own module?
  if trigger_specs:
    _trigger_builds(step_annotation, trigger_specs)

  return step_annotation, returncode


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

  @property
  def previous_step_result(self):
    """Allows api.step to get the active result from any context."""
    return self._previous_step_result

  def _emit_results(self):
    annotation = self._previous_step_annotation
    step_result = self._previous_step_result

    self._previous_step_annotation = None
    self._previous_step_result = None

    if not annotation or not step_result:
      return

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
    annotation.step_ended()

  def run_step(self, step):
    ok_ret = step.pop('ok_ret')
    infra_step = step.pop('infra_step')
    nest_level = step.pop('step_nest_level')

    test_data_fn = step.pop('step_test_data', recipe_test_api.StepTestData)
    step_test = self._test_data.pop_step_test_data(step['name'],
                                                   test_data_fn)
    placeholders = render_step(step, step_test)

    self._step_history[step['name']] = step
    self._emit_results()

    step_result = None

    if not self._test_data.enabled:
      self._previous_step_annotation, retcode = _run_annotated_step(
        self._stream, nest_level=nest_level, **step)

      step_result = StepData(step, retcode)
      self._stream.step_cursor(step['name'])
    else:
      self._previous_step_annotation = annotation = self._stream.step(
              step['name'])
      annotation.step_started()
      try:
        annotation.stream = cStringIO.StringIO()
        if nest_level:
          annotation.step_nest_level(nest_level)

        step_result = StepData(step, step_test.retcode)
      except OSError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        trace = traceback.format_exception(exc_type, exc_value, exc_tb)
        trace_lines = ''.join(trace).split('\n')
        annotation.write_log_lines('exception', filter(None, trace_lines))
        annotation.step_exception()

    get_placeholder_results(step_result, placeholders)
    self._previous_step_result = step_result

    if step_result.retcode in ok_ret:
      step_result.presentation.status = 'SUCCESS'
      return step_result
    else:
      if not infra_step:
        state = 'FAILURE'
        exc = recipe_api.StepFailure
      else:
        state = 'EXCEPTION'
        exc = recipe_api.InfraFailure

      step_result.presentation.status = state
      if step_test.enabled:
        # To avoid cluttering the expectations, don't emit this in testmode.
        self._previous_step_annotation.emit(
            'step returned non-zero exit code: %d' % step_result.retcode)

      raise exc(step['name'], step_result)


  def run(self, steps_function, api):
    self._api = api
    retcode = None
    final_result = None

    try:
      try:
        retcode = steps_function(api)
        assert retcode is None, (
        "Non-None return from GenSteps is not supported yet")

        assert not self._test_data.enabled or not self._test_data.step_data, (
        "Unconsumed test data! %s" % (self._test_data.step_data,))
      finally:
        self._emit_results()
    except recipe_api.StepFailure as f:
      retcode = f.retcode or 1
      final_result = {
        "name": "$final_result",
        "reason": f.reason,
        "status_code": retcode
      }
    except StepDataAttributeError as ex:
      unexpected_exception = self._test_data.is_unexpected_exception(ex)

      retcode = -1
      final_result = {
        "name": "$final_result",
        "reason": "Invalid Step Data Access: %r" % ex,
        "status_code": retcode
      }

      with self._stream.step('Invalid Step Data Access') as s:
        s.step_exception()
        s.write_log_lines('exception', traceback.format_exc().splitlines())

      if unexpected_exception:
        raise

    except Exception as ex:
      unexpected_exception = self._test_data.is_unexpected_exception(ex)

      retcode = -1
      final_result = {
        "name": "$final_result",
        "reason": "Uncaught Exception: %r" % ex,
        "status_code": retcode
      }

      with self._stream.step('Uncaught Exception') as s:
        s.step_exception()
        s.write_log_lines('exception', traceback.format_exc().splitlines())

      if unexpected_exception:
        raise

    if final_result is not None:
      self._step_history[final_result['name']] = final_result

    return RecipeExecutionResult(retcode, self._step_history)

  def create_step(self, step):  # pylint: disable=R0201
    # This version of engine doesn't do anything, just converts step to dict
    # (that is consumed by annotator engine).
    return step.as_jsonish()


