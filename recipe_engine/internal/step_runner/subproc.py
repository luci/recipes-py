# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import calendar
import contextlib
import datetime
import json
import os
import pprint
import re
import sys
import time
import traceback

from cStringIO import StringIO

import attr

from ... import recipe_api
from ... import recipe_test_api
from ... import types
from ... import util
from ...third_party import subprocess42

from .. import stream

from . import StepRunner, OpenStep
from . import construct_step_result, render_step, merge_envs


if sys.platform == "win32":
  # subprocess.Popen(close_fds) raises an exception when attempting to do this
  # and also redirect stdin/stdout/stderr. To be on the safe side, we just don't
  # do this on windows.
  CLOSE_FDS = False

  # Windows has a bad habit of opening a dialog when a console program
  # crashes, rather than just letting it crash.  Therefore, when a
  # program crashes on Windows, we don't find out until the build step
  # times out.  This code prevents the dialog from appearing, so that we
  # find out immediately and don't waste time waiting for a user to
  # close the dialog.
  import ctypes
  # SetErrorMode(
  #   SEM_FAILCRITICALERRORS|
  #   SEM_NOGPFAULTERRORBOX|
  #   SEM_NOOPENFILEERRORBOX
  # ).
  #
  # For more information, see:
  # https://msdn.microsoft.com/en-us/library/windows/desktop/ms680621.aspx
  ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)
else:
  # Non-windows platforms implement close_fds in a safe way.
  CLOSE_FDS = True


class _streamingLinebuf(object):
  def __init__(self):
    self.buffedlines = []
    self.extra = StringIO()

  def ingest(self, data):
    lines = data.splitlines()
    endedOnLinebreak = data.endswith("\n")

    if self.extra.tell():
      # we had leftovers from some previous ingest
      self.extra.write(lines[0])
      if len(lines) > 1 or endedOnLinebreak:
        lines[0] = self.extra.getvalue()
        self.extra = StringIO()
      else:
        return

    if not endedOnLinebreak:
      self.extra.write(lines[-1])
      lines = lines[:-1]

    self.buffedlines += lines

  def get_buffered(self):
    ret = self.buffedlines
    self.buffedlines = []
    return ret


class SubprocessStepRunner(StepRunner):
  """Responsible for actually running steps as subprocesses, filtering their
  output into a stream."""

  def __init__(self, stream_engine):
    self._stream_engine = stream_engine

  @property
  def stream_engine(self):
    return self._stream_engine

  def open_step(self, step_config):
    step_stream = self._stream_engine.new_step_stream(step_config)
    if not step_config.cmd:
      class EmptyOpenStep(OpenStep):
        # pylint: disable=no-self-argument
        def run(inner):
          if step_config.trigger_specs:
            self._trigger_builds(step_stream, step_config.trigger_specs)
          return types.StepData(step_config, 0)

        def finalize(inner):
          step_stream.close()

        @property
        def stream(inner):
          return step_stream

      return EmptyOpenStep()

    try:
      rendered_step = render_step(
          step_config, recipe_test_api.DisabledTestData()
      )
      step_config = None  # Make sure we use rendered step config.

      step_env = merge_envs(os.environ,
          rendered_step.config.env,
          rendered_step.config.env_prefixes.mapping,
          rendered_step.config.env_suffixes.mapping,
          rendered_step.config.env_prefixes.pathsep)  # just pick one

      # Now that the step's environment is all sorted, evaluate PATH on windows
      # to find the actual intended executable.
      cmd0 = util.hunt_path(rendered_step.config.cmd[0], step_env)
      if cmd0 != rendered_step.config.cmd[0]:
        rendered_step = rendered_step._replace(
          config=attr.evolve(rendered_step.config,
            cmd=(cmd0,)+rendered_step.config.cmd[1:],
          ),
        )

      self._print_step(step_stream, rendered_step, step_env)
    except:
      with self.stream_engine.make_step_stream('Step Preparation Exception') as s:
        s.set_step_status('EXCEPTION')
        with s.new_log_stream('exception') as l:
          l.write_split(traceback.format_exc())
      raise

    class ReturnOpenStep(OpenStep):
      # pylint: disable=no-self-argument
      def run(inner):
        step_config = rendered_step.config
        try:
          # Open file handles for IO redirection based on file names in
          # step_config.
          handles = {}
          fname = step_config.stdin
          handles['stdin'] = open(fname, 'rb') if fname else None

          fname = step_config.stdout
          handles['stdout'] = (
            open(fname, 'wb') if fname else step_stream.stdout.fileno())

          fname = step_config.stderr
          handles['stderr'] = (
            open(fname, 'wb') if fname else step_stream.stderr.fileno())

          # The subprocess will inherit and close these handles.
          retcode = self._run_cmd(
              cmd=step_config.cmd, timeout=step_config.timeout, handles=handles,
              env=step_env, cwd=step_config.cwd)
        except subprocess42.TimeoutExpired as e:
          #FIXME: Make this respect the infra_step argument
          step_stream.set_step_status('FAILURE')
          raise recipe_api.StepTimeout(step_config.name, e.timeout)
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

          if step_config.trigger_specs:
            self._trigger_builds(step_stream, step_config.trigger_specs)

        return construct_step_result(rendered_step, retcode)

      def finalize(inner):
        step_stream.close()

      @property
      def stream(inner):
        return step_stream

    return ReturnOpenStep()

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
      render_func = getattr(value, 'render_step_value',
                            lambda: pprint.pformat(value))
      return render_func()

    while hasattr(value, 'func'):
      value = value.func
    return getattr(value, '__name__', 'UNKNOWN_CALLABLE')+'(...)'

  def _print_step(self, step_stream, step, env):
    """Prints the step command and relevant metadata.

    Intended to be similar to the information that Buildbot prints at the
    beginning of each non-annotator step.
    """
    def gen_step_prelude():
      yield ' '.join(map(_shell_quote, step.config.cmd))
      cwd = step.config.cwd
      if cwd is None:
        try:
          cwd = os.getcwd()
        except OSError as ex:
          cwd = '??? (ENGINE START_DIR IS MISSING: %r)' % (ex,)
      elif not os.path.isdir(cwd):
          cwd += ' (MISSING OR NOT A DIR)'
      yield 'in dir %s:' % (cwd,)
      for key, value in sorted(attr.asdict(step.config).items()):
        if value is not None:
          yield ' %s: %s' % (key, self._render_step_value(value))
      yield 'full environment:'
      for key, value in sorted(env.items()):
        yield ' %s: %s' % (key, value)
      yield ''
    stream.output_iter(step_stream, gen_step_prelude())

  def _run_cmd(self, cmd, timeout, handles, env, cwd):
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
      handle = handles.get(key)
      if isinstance(handle, stream.StreamEngine.Stream):
        fhandles[key] = subprocess42.PIPE
      else:
        fhandles[key] = handle

    # stdin must be a real handle, if it exists
    fhandles['stdin'] = handles.get('stdin')

    with _modify_lookup_path(env.get('PATH')):
      proc = subprocess42.Popen(
          cmd,
          env=env,
          cwd=cwd,
          detached=True,
          universal_newlines=True,
          close_fds=CLOSE_FDS,
          **fhandles)

    # Safe to close file handles now that subprocess has inherited them.
    for handle in fhandles.itervalues():
      if isinstance(handle, file):
        handle.close()

    outstreams = {}
    linebufs = {}

    for key in ('stdout', 'stderr'):
      handle = handles.get(key)
      if isinstance(handle, stream.StreamEngine.Stream):
        outstreams[key] = handle
        linebufs[key] = _streamingLinebuf()

    if linebufs:
      # manually check the timeout, because we poll
      start_time = time.time()
      for pipe, data in proc.yield_any(timeout=1):
        if timeout and time.time() - start_time > timeout:
          # Don't know the name of the step, so raise this and it'll get caught
          raise subprocess42.TimeoutExpired(cmd, timeout)

        if pipe is None:
          continue
        buf = linebufs.get(pipe)
        if not buf:
          continue
        buf.ingest(data)
        for line in buf.get_buffered():
          outstreams[pipe].write_line(line)
    else:
      proc.wait(timeout)

    return proc.returncode

  def _trigger_builds(self, step, trigger_specs):
    assert trigger_specs is not None
    for trig in trigger_specs:
      builder_name = trig.builder_name
      if not builder_name:
        raise ValueError('Trigger spec: builder_name is not set')

      changes = trig.buildbot_changes or []
      assert isinstance(changes, list), 'buildbot_changes must be a list'
      changes = map(self._normalize_change, changes)

      step.trigger(json.dumps({
          'builderNames': [builder_name],
          'bucket': trig.bucket,
          'changes': changes,
          # if True and triggering fails asynchronously, fail entire build.
          'critical': trig.critical,
          'properties': trig.properties,
          'tags': trig.tags,
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
