#!/usr/bin/env python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contains generating and parsing systems of the Chromium Buildbot Annotator.

When executed as a script, this reads step name / command pairs from a file and
executes those lines while annotating the output. The input is json:

[{"name": "step_name", "cmd": ["command", "arg1", "arg2"]},
 {"name": "step_name2", "cmd": ["command2", "arg1"]}]

"""

import contextlib
import json
import optparse
import os
import subprocess
import sys
import threading
import traceback


# These are maps of annotation key -> number of expected arguments.
STEP_ANNOTATIONS = {
    'SET_BUILD_PROPERTY': 2,
    'STEP_CLEAR': 0,
    'STEP_EXCEPTION': 0,
    'STEP_FAILURE': 0,
    'STEP_LINK': 2,
    'STEP_LOG_END': 1,
    'STEP_LOG_END_PERF': 2,
    'STEP_LOG_LINE': 2,
    'STEP_SUMMARY_CLEAR': 0,
    'STEP_SUMMARY_TEXT': 1,
    'STEP_TEXT': 1,
    'STEP_TRIGGER': 1,
    'STEP_WARNINGS': 0,
}

CONTROL_ANNOTATIONS = {
    'STEP_CLOSED': 0,
    'STEP_STARTED': 0,
}

STREAM_ANNOTATIONS = {
    'HALT_ON_FAILURE': 0,
    'HONOR_ZERO_RETURN_CODE': 0,
    'SEED_STEP': 1,
    'SEED_STEP_TEXT': 2,
    'STEP_CURSOR': 1,
}

DEPRECATED_ANNOTATIONS = {
    'BUILD_STEP': 1,
}

ALL_ANNOTATIONS = {}
ALL_ANNOTATIONS.update(STEP_ANNOTATIONS)
ALL_ANNOTATIONS.update(CONTROL_ANNOTATIONS)
ALL_ANNOTATIONS.update(STREAM_ANNOTATIONS)
ALL_ANNOTATIONS.update(DEPRECATED_ANNOTATIONS)

# This is a mapping of old_annotation_name -> new_annotation_name.
# Theoretically all annotator scripts should use the new names, but it's hard
# to tell due to the decentralized nature of the annotator.
DEPRECATED_ALIASES = {
    'BUILD_FAILED': 'STEP_FAILURE',
    'BUILD_WARNINGS': 'STEP_WARNINGS',
    'BUILD_EXCEPTION': 'STEP_EXCEPTION',
    'link': 'STEP_LINK',
}

# A couple of the annotations have the format:
#  @@@THING arg@@@
# for reasons no one knows. We only need this case until all masters have been
# restarted to pick up the new master-side parsing code.
OLD_STYLE_ANNOTATIONS = set((
  'SEED_STEP',
  'STEP_CURSOR',
))


def emit(line, stream, flush_before=None):
  if flush_before:
    flush_before.flush()
  print >> stream
  # WinDOS can only handle 64kb of output to the console at a time, per process.
  if sys.platform.startswith('win'):
    lim = 2**15
    while line:
      to_print, line = line[:lim], line[lim:]
      stream.write(to_print)
    stream.write('\n')
  else:
    print >> stream, line
  stream.flush()


class MetaAnnotationPrinter(type):
  def __new__(mcs, name, bases, dct):
    annotation_map = dct.get('ANNOTATIONS')
    if annotation_map:
      for key, v in annotation_map.iteritems():
        key = key.lower()
        dct[key] = mcs.make_printer_fn(key, v)
    return type.__new__(mcs, name, bases, dct)

  @staticmethod
  def make_printer_fn(name, n_args):
    """Generates a method which emits an annotation to the log stream."""
    upname = name.upper()
    if upname in OLD_STYLE_ANNOTATIONS:
      assert n_args >= 1
      fmt = '@@@%s %%s%s@@@' % (upname, '@%s' * (n_args - 1))
    else:
      fmt = '@@@%s%s@@@' % (upname, '@%s' * n_args)

    inner_args = n_args + 1  # self counts
    infix = '1 argument' if inner_args == 1 else ('%d arguments' % inner_args)
    err = '%s() takes %s (%%d given)' % (name, infix)

    def printer(self, *args):
      if len(args) != n_args:
        raise TypeError(err % (len(args) + 1))
      self.emit(fmt % args)
    printer.__name__ = name
    printer.__doc__ = """Emits an annotation for %s.""" % name.upper()

    return printer


class AnnotationPrinter(object):
  """A derivable class which will inject annotation-printing methods into the
  subclass.

  A subclass should define a class variable ANNOTATIONS equal to a
  dictionary of the form { '<ANNOTATION_NAME>': <# args> }. This class will
  then inject methods whose names are the undercased version of your
  annotation names, and which take the number of arguments specified in the
  dictionary.

  Example:
    >>> my_annotations = { 'STEP_LOG_LINE': 2 }
    >>> class MyObj(AnnotationPrinter):
    ...   ANNOTATIONS = my_annotations
    ...
    >>> o = MyObj()
    >>> o.step_log_line('logname', 'here is a line to put in the log')
    @@@STEP_LOG_LINE@logname@here is a line to put in the log@@@
    >>> o.step_log_line()
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
    TypeError: step_log_line() takes exactly 3 arguments (1 given)
    >>> o.setp_log_line.__doc__
    "Emits an annotation for STEP_LOG_LINE."
    >>>
  """
  __metaclass__ = MetaAnnotationPrinter

  def __init__(self, stream, flush_before):
    self.stream = stream
    self.flush_before = flush_before

  def emit(self, line):
    emit(line, self.stream, self.flush_before)


class StepCommands(AnnotationPrinter):
  """Class holding step commands. Intended to be subclassed."""
  ANNOTATIONS = STEP_ANNOTATIONS

  def __init__(self, stream, flush_before):
    super(StepCommands, self).__init__(stream, flush_before)
    self.emitted_logs = set()

  def write_log_lines(self, logname, lines, perf=None):
    if logname in self.emitted_logs:
      raise ValueError('Log %s has been emitted multiple times.' % logname)
    self.emitted_logs.add(logname)

    for line in lines:
      self.step_log_line(logname, line)
    if perf:
      self.step_log_end_perf(logname, perf)
    else:
      self.step_log_end(logname)

class StepControlCommands(AnnotationPrinter):
  """Subclass holding step control commands. Intended to be subclassed.

  This is subclassed out so callers in StructuredAnnotationStep can't call
  step_started() or step_closed().
  """
  ANNOTATIONS = CONTROL_ANNOTATIONS


class StructuredAnnotationStep(StepCommands):
  """Helper class to provide context for a step."""

  def __init__(self, annotation_stream, *args, **kwargs):
    self.annotation_stream = annotation_stream
    super(StructuredAnnotationStep, self).__init__(*args, **kwargs)
    self.control = StepControlCommands(self.stream, self.flush_before)
    self.emitted_logs = set()


  def __enter__(self):
    return self.step_started()

  def step_started(self):
    self.control.step_started()
    return self

  def __exit__(self, exc_type, exc_value, tb):
    self.annotation_stream.step_cursor(self.annotation_stream.current_step)
    #TODO(martinis) combine this and step_ended
    if exc_type:
      self.step_exception_occured(exc_type, exc_value, tb)

    self.control.step_closed()
    self.annotation_stream.current_step = ''
    return not exc_type

  def step_exception_occured(self, exc_type, exc_value, tb):
    trace = traceback.format_exception(exc_type, exc_value, tb)
    trace_lines = ''.join(trace).split('\n')
    self.write_log_lines('exception', filter(None, trace_lines))
    self.step_exception()

  def step_ended(self):
    self.annotation_stream.step_cursor(self.annotation_stream.current_step)
    self.control.step_closed()
    self.annotation_stream.current_step = ''

    return True

class AdvancedAnnotationStep(StepCommands, StepControlCommands):
  """Holds additional step functions for finer step control.

  Most users will want to use StructuredAnnotationSteps generated from a
  StructuredAnnotationStream as these handle state automatically.
  """

  def __init__(self, *args, **kwargs):
    super(AdvancedAnnotationStep, self).__init__(*args, **kwargs)


class AdvancedAnnotationStream(AnnotationPrinter):
  """Holds individual annotation generating functions for streams.

  Most callers should use StructuredAnnotationStream to simplify coding and
  avoid errors. For the rare cases where StructuredAnnotationStream is
  insufficient (parallel step execution), the individual functions are exposed
  here.
  """
  ANNOTATIONS = STREAM_ANNOTATIONS


class StructuredAnnotationStream(AdvancedAnnotationStream):
  """Provides an interface to handle an annotated build.

  StructuredAnnotationStream handles most of the step setup and closure calls
  for you. All you have to do is execute your code within the steps and set any
  failures or warnings that come up. You may optionally provide a list of steps
  to seed before execution.

  Usage:

  stream = StructuredAnnotationStream()
  with stream.step('compile') as s:
    # do something
    if error:
      s.step_failure()
  with stream.step('test') as s:
    # do something
    if warnings:
      s.step_warnings()
  """

  def __init__(self, stream=sys.stdout,
               flush_before=sys.stderr,
               seed_steps=None):  # pylint: disable=W0613
    super(StructuredAnnotationStream, self).__init__(stream=stream,
                                                     flush_before=flush_before)
    self.current_step = ''

  def step(self, name):
    """Provide a context with which to execute a step."""
    if self.current_step:
      raise Exception('Can\'t start step %s while in step %s.' % (
          name, self.current_step))

    self.seed_step(name)
    self.step_cursor(name)
    self.current_step = name
    return StructuredAnnotationStep(self, stream=self.stream,
                                    flush_before=self.flush_before)


def MatchAnnotation(line, callback_implementor):
  """Call back into |callback_implementor| if line contains an annotation.

  Args:
    line (str) - The line to analyze
    callback_implementor (object) - An object which contains methods
      corresponding to all of the annotations in the |ALL_ANNOTATIONS|
      dictionary. For example, it should contain a method STEP_SUMMARY_TEXT
      taking a single argument.

  Parsing method:
    * if line doesn't match /^@@@.*@@@$/, return without calling back
    * Look for the first '@' or ' '
  """
  if not (line.startswith('@@@') and line.endswith('@@@') and len(line) > 6):
    return
  line = line[3:-3]

  # look until the first @ or ' '
  idx = min((x for x in (line.find('@'), line.find(' '), len(line)) if x > 0))
  cmd_text = line[:idx]
  cmd = DEPRECATED_ALIASES.get(cmd_text, cmd_text)

  field_count = ALL_ANNOTATIONS.get(cmd)
  if field_count is None:
    raise Exception('Unrecognized annotator command "%s"' % cmd_text)

  if field_count:
    if idx == len(line):
      raise Exception('Annotator command "%s" expects %d args, got 0.'
                      % (cmd_text, field_count))

    line = line[idx+1:]

    args = line.split('@', field_count-1)
    if len(args) != field_count:
      raise Exception('Annotator command "%s" expects %d args, got %d.'
                      % (cmd_text, field_count, len(args)))
  else:
    line = line[len(cmd_text):]
    if line:
      raise Exception('Annotator command "%s" expects no args, got cruft "%s".'
                      % (cmd_text, line))
    args = []

  fn = getattr(callback_implementor, cmd, None)
  if fn is None:
    raise Exception('"%s" does not implement "%s"'
                    % (callback_implementor, cmd))

  fn(*args)


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


def _validate_step(step):
  """Validates parameters of the step.
  Returns None if it's OK, error message if not.
  """
  for req in ['cmd', 'name']:
    if req not in step:
      return 'missing \'%s\' parameter' % (req,)
  if 'cwd' in step and not os.path.isabs(step['cwd']):
    return '\'cwd\' should be an absolute path'
  return None


def print_step(step, env, stream):
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
def modify_lookup_path(path):
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


def triggerBuilds(step, trigger_specs):
  assert trigger_specs is not None
  for trig in trigger_specs:
    props = trig.get('properties')
    if not props:
      raise ValueError('Trigger spec: properties are missing')
    builder_name = props.pop('buildername', None)
    if not builder_name:
      raise ValueError('Trigger spec: buildername property is missing')
    step.step_trigger(json.dumps({
        'builderNames': [builder_name],
        # Handle case where trig['properties'] is Falsy
        'properties': props,
    }))


def run_step(stream, name, cmd,
             cwd=None, env=None,
             allow_subannotations=False,
             trigger_specs=None,
             **kwargs):
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

  print_step(step_dict, step_env, stream)
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

      with modify_lookup_path(step_env.get('PATH')):
        proc = subprocess.Popen(
            cmd,
            env=step_env,
            cwd=cwd,
            universal_newlines=True,
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
    triggerBuilds(step_annotation, trigger_specs)

  return step_annotation, returncode

def update_build_failure(failure, retcode, **_kwargs):
  """Potentially moves failure from False to True, depending on returncode of
  the run step and the step's configuration.

  can_fail_build: A boolean indicating that a bad retcode for this step should
                  be intepreted as a build failure.

  Returns new value for failure.

  Called externally from annotated_run, which is why it's a separate function.
  """
  # TODO(iannucci): Allow step to specify "OK" return values besides 0?
  return failure or retcode

def run_steps(steps, build_failure):
  for step in steps:
    error = _validate_step(step)
    if error:
      print 'Invalid step - %s\n%s' % (error, json.dumps(step, indent=2))
      sys.exit(1)

  stream = StructuredAnnotationStream()
  ret_codes = []
  build_failure = False
  prev_annotation = None
  for step in steps:
    if build_failure and not step.get('always_run', False):
      ret = None
    else:
      prev_annotation, ret = run_step(stream, **step)
      stream = prev_annotation.annotation_stream
      if ret > 0:
        stream.step_cursor(stream.current_step)
        stream.emit('step returned non-zero exit code: %d' % ret)
        prev_annotation.step_failure()

      prev_annotation.step_ended()
    build_failure = update_build_failure(build_failure, ret)
    ret_codes.append(ret)
  if prev_annotation:
    prev_annotation.step_ended()
  return build_failure, ret_codes


def main():
  usage = '%s <command list file or - for stdin>' % sys.argv[0]
  parser = optparse.OptionParser(usage=usage)
  _, args = parser.parse_args()
  if not args:
    parser.error('Must specify an input filename.')
  if len(args) > 1:
    parser.error('Too many arguments specified.')

  steps = []

  def force_list_str(lst):
    ret = []
    for v in lst:
      if isinstance(v, basestring):
        v = str(v)
      elif isinstance(v, list):
        v = force_list_str(v)
      elif isinstance(v, dict):
        v = force_dict_strs(v)
      ret.append(v)
    return ret

  def force_dict_strs(obj):
    ret = {}
    for k, v in obj.iteritems():
      if isinstance(v, basestring):
        v = str(v)
      elif isinstance(v, list):
        v = force_list_str(v)
      elif isinstance(v, dict):
        v = force_dict_strs(v)
      ret[str(k)] = v
    return ret

  if args[0] == '-':
    steps.extend(json.load(sys.stdin, object_hook=force_dict_strs))
  else:
    with open(args[0], 'rb') as f:
      steps.extend(json.load(f, object_hook=force_dict_strs))

  return 1 if run_steps(steps, False)[0] else 0


if __name__ == '__main__':
  sys.exit(main())
