# Copyright (c) 2013-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import cStringIO
import collections
import contextlib
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import traceback

from . import recipe_test_api
from . import stream
from . import types
from . import util

class StepRunner(object):
  """A StepRunner is the interface to actually running steps.

  These can actually make subprocess calls (SubprocessStepRunner), or just
  pretend to run the steps with mock output (SimulationStepRunner).
  """
  @property
  def stream_engine(self):
    """Return the stream engine that this StepRunner uses, if meaningful.

    Users of this method must be prepared to handle None.
    """
    return None

  def open_step(self, step_dict):
    """Constructs an OpenStep object which can be used to actually run a step.

    step_dict parameters:
      name: name of the step, will appear in buildbots waterfall
      cmd: command to run, list of one or more strings
      cwd: absolute path to working directory for the command
      env: dict with overrides for environment variables
      allow_subannotations: if True, lets the step emit its own annotations
      trigger_specs: a list of trigger specifications, which are dict with keys:
          properties: a dict of properties.
              Buildbot requires buildername property.
      stdout: Path to a file to put step stdout into. If used, stdout won't
              appear in annotator's stdout (and |allow_subannotations| is
              ignored).
      stderr: Path to a file to put step stderr into. If used, stderr won't
              appear in annotator's stderr.
      stdin: Path to a file to read step stdin from.

    Returns an OpenStep object.
    """
    raise NotImplementedError()

  def run_recipe(self, universe, recipe, properties):
    """Run the recipe named |recipe|.

    Args:
      universe: The RecipeUniverse where the recipe lives.
      recipe: The recipe name (e.g. 'infra/luci_py')
      properties: a dictionary of properties to pass to the recipe

    Returns the recipe result.
    """
    raise NotImplementedError()

  @contextlib.contextmanager
  def run_context(self):
    """A context in which the entire engine run takes place.

    This is typically used to catch exceptions thrown by the recipe.
    """
    yield


class OpenStep(object):
  """An object that can be used to run a step.

  We use this object instead of just running directly because, after a step
  is run, it stays open (can be modified with step_text and links and things)
  until another step at its nest level or lower is started.
  """
  def run(self):
    """Starts the step, running its command."""
    raise NotImplementedError()

  def finalize(self):
    """Closes the step and finalizes any stored presentation."""
    raise NotImplementedError()

  @property
  def stream(self):
    """The stream.StepStream that this step is using for output.

    It is permitted to use this stream between run() and finalize() calls. """
    raise NotImplementedError()


class SubprocessStepRunner(StepRunner):
  """Responsible for actually running steps as subprocesses, filtering their
  output into a stream."""

  def __init__(self, stream_engine):
    self._stream_engine = stream_engine

  @property
  def stream_engine(self):
    return self._stream_engine

  def open_step(self, step_dict):
    allow_subannotations = step_dict.get('allow_subannotations', False)
    step_stream = self._stream_engine.new_step_stream(
        step_dict['name'],
        allow_subannotations=allow_subannotations)
    if not step_dict.get('cmd'):
      class EmptyOpenStep(OpenStep):
        def run(inner):
          if 'trigger_specs' in step_dict:
            self._trigger_builds(step_stream, step_dict['trigger_specs'])
          return types.StepData(step_dict, 0)

        def finalize(inner):
          step_stream.close()

        @property
        def stream(inner):
          return step_stream

      return EmptyOpenStep()

    step_dict, placeholders = render_step(
        step_dict, recipe_test_api.DisabledTestData())
    cmd = map(str, step_dict['cmd'])
    step_env = _merge_envs(os.environ, step_dict.get('env', {}))
    if 'nest_level' in step_dict:
      step_stream.step_nest_level(step_dict['nest_level'])
    self._print_step(step_stream, step_dict, step_env)

    class ReturnOpenStep(OpenStep):
      def run(inner):
        try:
          # Open file handles for IO redirection based on file names in
          # step_dict.
          handles = {
            'stdout': step_stream,
            'stderr': step_stream,
            'stdin': None,
          }
          for key in handles:
            if key in step_dict:
              handles[key] = open(step_dict[key],
                                   'rb' if key == 'stdin' else 'wb')
          # The subprocess will inherit and close these handles.
          retcode = self._run_cmd(
              cmd=cmd, handles=handles, env=step_env, cwd=step_dict.get('cwd'))
        except OSError:
          with step_stream.new_log_stream('exception') as l:
            trace = traceback.format_exc().splitlines()
            for line in trace:
              l.write_line(line)
          step_stream.set_step_status('EXCEPTION')
          raise
        finally:
          # NOTE(luqui) See the accompanying note in stream.py.
          step_stream.reset_subannotation_state()

          if 'trigger_specs' in step_dict:
            self._trigger_builds(step_stream, step_dict['trigger_specs'])

        return construct_step_result(step_dict, retcode, placeholders)

      def finalize(inner):
        step_stream.close()

      @property
      def stream(inner):
        return step_stream

    return ReturnOpenStep()

  def run_recipe(self, universe, recipe, properties):
    with tempfile.NamedTemporaryFile() as f:
      cmd = [sys.executable,
             universe.package_deps.engine_recipes_py,
             '--package=%s' % universe.config_file, 'run',
             '--output-result-json=%s' % f.name, recipe]
      cmd.extend(['%s=%s' % (k,repr(v)) for k, v in properties.iteritems()])

      retcode = subprocess.call(cmd)
      result = json.load(f)
      if retcode != 0:
        raise recipe_api.StepFailure(
          'depend on %s with properties %r failed with %d.\n'
          'Recipe result: %r' % (
              recipe, properties, retcode, result))
      return result

  @contextlib.contextmanager
  def run_context(self):
    """Swallow exceptions -- they will be captured and reported in the
    RecipeResult"""
    try:
      yield
    except Exception:
      pass

  def _render_step_value(self, value):
    if not callable(value):
      return value

    while hasattr(value, 'func'):
      value = value.func
    return getattr(value, '__name__', 'UNKNOWN_CALLABLE')+'(...)'

  def _print_step(self, step_stream, step, env):
    """Prints the step command and relevant metadata.

    Intended to be similar to the information that Buildbot prints at the
    beginning of each non-annotator step.
    """
    step_stream.write_line(' '.join(map(_shell_quote, step['cmd'])))
    step_stream.write_line('in dir %s:' % (step.get('cwd') or os.getcwd()))
    for key, value in sorted(step.items()):
      if value is not None:
        step_stream.write_line(
            ' %s: %s' % (key, self._render_step_value(value)))
    step_stream.write_line('full environment:')
    for key, value in sorted(env.items()):
      step_stream.write_line(' %s: %s' % (key, value))
    step_stream.write_line('')

  def _run_cmd(self, cmd, handles, env, cwd):
    """Runs cmd (subprocess-style).

    Args:
      cmd: a subprocess-style command list, with command first then args.
      handles: A dictionary from ('stdin', 'stdout', 'stderr'), each value
        being *either* a stream.StreamEngine.Stream or a python file object
        to direct that subprocess's filehandle to.
      env: the full environment to run the command in -- this is passed
        unaltered to subprocess.Popen.
      cwd: the working directory of the command.
    """
    fhandles = {}

    # If we are given StreamEngine.Streams, map them to PIPE for subprocess.
    # We will manually forward them to their corresponding stream.
    for key in ('stdout', 'stderr'):
      if (key in handles and
          isinstance(handles[key], stream.StreamEngine.Stream)):
        fhandles[key] = subprocess.PIPE
      else:
        fhandles[key] = handles[key]

    # stdin must be a real handle, if it exists
    fhandles['stdin'] = handles.get('stdin')

    if sys.platform.startswith('win'):
      # Windows has a bad habit of opening a dialog when a console program
      # crashes, rather than just letting it crash.  Therefore, when a
      # program crashes on Windows, we don't find out until the build step
      # times out.  This code prevents the dialog from appearing, so that we
      # find out immediately and don't waste time waiting for a user to
      # close the dialog.
      import ctypes
      # SetErrorMode(SEM_NOGPFAULTERRORBOX). For more information, see:
      # https://msdn.microsoft.com/en-us/library/windows/desktop/ms680621.aspx
      ctypes.windll.kernel32.SetErrorMode(0x0002)
      # CREATE_NO_WINDOW. For more information, see:
      # https://msdn.microsoft.com/en-us/library/windows/desktop/ms684863.aspx
      creationflags = 0x8000000
    else:
      creationflags = 0

    with _modify_lookup_path(env.get('PATH')):
      proc = subprocess.Popen(
          cmd,
          env=env,
          cwd=cwd,
          universal_newlines=True,
          creationflags=creationflags,
          **fhandles)

    # Safe to close file handles now that subprocess has inherited them.
    for handle in fhandles.itervalues():
      if isinstance(handle, file):
        handle.close()

    outlock = threading.Lock()
    def make_pipe_thread(inhandle, outstream):
      def body():
        while True:
          line = inhandle.readline()
          if not line:
            break
          line = line[:-1] # Strip newline for write_line's expectations
                           # (universal_newlines is on, so it's only \n)
          outlock.acquire()
          try:
            outstream.write_line(line)
          finally:
            outlock.release()
      return threading.Thread(target=body, args=())

    threads = []
    for key in ('stdout', 'stderr'):
      if (key in handles and
          isinstance(handles[key], stream.StreamEngine.Stream)):
        threads.append(make_pipe_thread(getattr(proc, key), handles[key]))

    for th in threads:
      th.start()
    proc.wait()
    for th in threads:
      th.join()
    return proc.returncode

  def _trigger_builds(self, step, trigger_specs):
    assert trigger_specs is not None
    for trig in trigger_specs:
      builder_name = trig.get('builder_name')
      if not builder_name:
        raise ValueError('Trigger spec: builder_name is not set')

      changes = trig.get('buildbot_changes', [])
      assert isinstance(changes, list), 'buildbot_changes must be a list'
      changes = map(self._normalize_change, changes)

      step.trigger(json.dumps({
          'builderNames': [builder_name],
          'bucket': trig.get('bucket'),
          'changes': changes,
          'properties': trig.get('properties'),
          'tags': trig.get('tags'),
      }, sort_keys=True))

  def _normalize_change(self, change):
    assert isinstance(change, dict), 'Change is not a dict'
    change = change.copy()

    # Convert when_timestamp to UNIX timestamp.
    when = change.get('when_timestamp')
    if isinstance(when, datetime.datetime):
      when = calendar.timegm(when.utctimetuple())
      change['when_timestamp'] = when

    return change


class SimulationStepRunner(StepRunner):
  """Pretends to run steps, instead recording what would have been run.

  This is the main workhorse of recipes.py simulation_test.  Returns the log of
  steps that would have been run in steps_ran.  Uses test_data to mock return
  values.
  """
  def __init__(self, stream_engine, test_data):
    self._test_data = test_data
    self._stream_engine = stream_engine
    self._step_history = collections.OrderedDict()

  @property
  def stream_engine(self):
    return self._stream_engine

  def open_step(self, step_dict):
    # We modify step_dict.  In particular, we add ~followup_annotations during
    # finalize, and depend on that side-effect being carried into what we
    # added to self._step_history, earlier.  So copy it here so at least we
    # keep the modifications local.
    step_dict = dict(step_dict)

    test_data_fn = step_dict.pop('step_test_data', recipe_test_api.StepTestData)
    step_test = self._test_data.pop_step_test_data(
        step_dict['name'], test_data_fn)
    step_dict, placeholders = render_step(step_dict, step_test)
    outstream = cStringIO.StringIO()

    # Layer the simulation step on top of the given stream engine.
    step_stream = stream.ProductStreamEngine.StepStream(
        self._stream_engine.new_step_stream(step_dict['name']),
        stream.BareAnnotationStepStream(outstream))

    class ReturnOpenStep(OpenStep):
      def run(inner):
        self._step_history[step_dict['name']] = step_dict
        return construct_step_result(step_dict, step_test.retcode, placeholders)

      def finalize(inner):
        # note that '~' sorts after 'z' so that this will be last on each
        # step. also use _step to get access to the mutable step
        # dictionary.
        lines = filter(None, outstream.getvalue().splitlines())
        if lines:
          # This magically floats into step_history, which we have already
          # added step_dict to.
          step_dict['~followup_annotations'] = lines

      @property
      def stream(inner):
        return step_stream

    return ReturnOpenStep()

  def run_recipe(self, universe, recipe, properties):
    return self._test_data.depend_on_data.pop(types.freeze((recipe, properties),))

  @contextlib.contextmanager
  def run_context(self):
    try:
      yield

      assert self._test_data.consumed, (
          "Unconsumed test data for steps: %s" % (
              self._test_data.step_data.keys(),))
    except Exception as ex:
      with self._test_data.should_raise_exception(ex) as should_raise:
        if should_raise:
          raise

  @property
  def steps_ran(self):
    return self._step_history.values()


# Result of 'render_step'.
Placeholders = collections.namedtuple(
    'Placeholders', ['cmd', 'stdout', 'stderr', 'stdin'])


def render_step(step, step_test):
  """Renders a step so that it can be fed to annotator.py.

  Args:
    step: The step to render.
    step_test: The test data json dictionary for this step, if any.
               Passed through unaltered to each placeholder.

  Returns the rendered step and a Placeholders object representing any
  placeholder instances that were found while rendering.
  """
  rendered_step = dict(step)

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
  rendered_step['cmd'] = new_cmd

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
      rendered_step[key] = placeholder.backing_file
    stdio_placeholders[key] = (placeholder, tdata)

  return rendered_step, Placeholders(cmd=placeholders, **stdio_placeholders)


def construct_step_result(step, retcode, placeholders):
  """Constructs a StepData step result from step return data.

  The main purpose of this function is to add placeholder results into the
  step result where placeholders appeared in the input step.
  """

  step_result = types.StepData(step, retcode)

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

  return step_result


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


def _shell_quote(arg):
  """Shell-quotes a string with minimal noise.

  Such that it is still reproduced exactly in a bash/zsh shell.
  """

  arg = arg.encode('utf-8')

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
