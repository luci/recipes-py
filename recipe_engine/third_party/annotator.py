# Copyright (c) 2013-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contains the parsing system of the Chromium Buildbot Annotator."""

import os
import sys
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
    'STEP_NEST_LEVEL': 1,
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

    logname = logname.replace('/', '&#x2f;')

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


class StructuredAnnotationStep(StepCommands, StepControlCommands):
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


class StructuredAnnotationStream(AnnotationPrinter):
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
  ANNOTATIONS = STREAM_ANNOTATIONS

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
