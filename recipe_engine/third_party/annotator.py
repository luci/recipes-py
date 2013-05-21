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

import json
import optparse
import os
import re
import sys
import traceback

from common import chromium_utils


def emit(line, stream, flush_before=None):
  if flush_before:
    flush_before.flush()
  print >> stream, '\n' + line
  stream.flush()


class StepCommands(object):
  """Class holding step commands. Intended to be subclassed."""
  def __init__(self, stream, flush_before):
    self.stream = stream
    self.flush_before = flush_before

  def emit(self, line):
    emit(line, self.stream, self.flush_before)

  def step_warnings(self):
    self.emit('@@@STEP_WARNINGS@@@')

  def step_failure(self):
    self.emit('@@@STEP_FAILURE@@@')

  def step_exception(self):
    self.emit('@@@STEP_EXCEPTION@@@')

  def step_clear(self):
    self.emit('@@@STEP_CLEAR@@@')

  def step_summary_clear(self):
    self.emit('@@@STEP_SUMMARY_CLEAR@@@')

  def step_text(self, text):
    self.emit('@@@STEP_TEXT@%s@@@' % text)

  def step_summary_text(self, text):
    self.emit('@@@STEP_SUMMARY_TEXT@%s@@@' % text)

  def step_log_line(self, logname, line):
    self.emit('@@@STEP_LOG_LINE@%s@%s@@@' % (logname, line.rstrip('\n')))

  def step_log_end(self, logname):
    self.emit('@@@STEP_LOG_END@%s@@@' % logname)

  def step_log_end_perf(self, logname, perf):
    self.emit('@@@STEP_LOG_END_PERF@%s@%s@@@' % (logname, perf))

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


class StepControlCommands(object):
  """Subclass holding step control commands. Intended to be subclassed.

  This is subclassed out so callers in StructuredAnnotationStep can't call
  step_started() or step_closed().
  """
  def __init__(self, stream, flush_before):
    self.stream = stream
    self.flush_before = flush_before

  def emit(self, line):
    emit(line, self.stream, self.flush_before)

  def step_started(self):
    self.emit('@@@STEP_STARTED@@@')

  def step_closed(self):
    self.emit('@@@STEP_CLOSED@@@')


class StructuredAnnotationStep(StepCommands):
  """Helper class to provide context for a step."""

  def __init__(self, annotation_stream, *args, **kwargs):
    self.annotation_stream = annotation_stream
    super(StructuredAnnotationStep, self).__init__(*args, **kwargs)
    self.control = StepControlCommands(self.stream, self.flush_before)
    self.emitted_logs = set()

  def __enter__(self):
    self.control.step_started()
    return self

  def __exit__(self, exc_type, exc_value, tb):
    if exc_type:
      trace = traceback.format_exception(exc_type, exc_value, tb)
      trace_lines = ''.join(trace).split('\n')
      self.write_log_lines('exception', filter(None, trace_lines))
      self.step_exception()

    self.control.step_closed()
    self.annotation_stream.current_step = ''
    return not exc_type

class AdvancedAnnotationStep(StepCommands, StepControlCommands):
  """Holds additional step functions for finer step control.

  Most users will want to use StructuredAnnotationSteps generated from a
  StructuredAnnotationStream as these handle state automatically.
  """

  def __init__(self, *args, **kwargs):
    super(AdvancedAnnotationStep, self).__init__(*args, **kwargs)


class AdvancedAnnotationStream(object):
  """Holds individual annotation generating functions for streams.

  Most callers should use StructuredAnnotationStream to simplify coding and
  avoid errors. For the rare cases where StructuredAnnotationStream is
  insufficient (parallel step execution), the indidividual functions are exposed
  here.
  """

  def __init__(self, stream=sys.stdout, flush_before=sys.stderr):
    self.stream = stream
    self.flush_before = flush_before

  def emit(self, line):
    emit(line, self.stream, self.flush_before)

  def seed_step(self, step):
    self.emit('@@@SEED_STEP %s@@@' % step)

  def step_cursor(self, step):
    self.emit('@@@STEP_CURSOR %s@@@' % step)

  def halt_on_failure(self):
    self.emit('@@@HALT_ON_FAILURE@@@')

  def honor_zero_return_code(self):
    self.emit('@@@HONOR_ZERO_RETURN_CODE@@@')


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

  def __init__(self, seed_steps=None, stream=sys.stdout,
               flush_before=sys.stderr):
    super(StructuredAnnotationStream, self).__init__(stream=stream,
                                                     flush_before=flush_before)
    seed_steps = seed_steps or []
    self.seed_steps = seed_steps

    for step in seed_steps:
      self.seed_step(step)

    self.current_step = ''

  def step(self, name):
    """Provide a context with which to execute a step."""
    if self.current_step:
      raise Exception('Can\'t start step %s while in step %s.' % (
          name, self.current_step))
    if name in self.seed_steps:
      # Seek ahead linearly, skipping steps that weren't emitted in order.
      # chromium_step.AnnotatedCommands uses the last in case of duplicated
      # step names, so we do the same here.
      idx = len(self.seed_steps) - self.seed_steps[::-1].index(name)
      self.seed_steps = self.seed_steps[idx:]
    else:
      self.seed_step(name)

    self.step_cursor(name)
    self.current_step = name
    return StructuredAnnotationStep(self, stream=self.stream,
                                    flush_before=self.flush_before)


class Match:
  """Holds annotator line parsing functions."""

  def __init__(self):
    raise Exception('Don\'t instantiate the Match class!')

  @staticmethod
  def _parse_line(regex, line):
    m = re.match(regex, line)
    if m:
      return list(m.groups())
    else:
      return []

  @staticmethod
  def log_line(line):
    return Match._parse_line('^@@@STEP_LOG_LINE@(.*)@(.*)@@@', line)

  @staticmethod
  def log_end(line):
    return Match._parse_line('^@@@STEP_LOG_END@(.*)@@@', line)

  @staticmethod
  def log_end_perf(line):
    return Match._parse_line('^@@@STEP_LOG_END_PERF@(.*)@(.*)@@@', line)

  @staticmethod
  def step_link(line):
    m = Match._parse_line('^@@@STEP_LINK@(.*)@(.*)@@@', line)
    if not m:
      return Match._parse_line('^@@@link@(.*)@(.*)@@@', line)  # Deprecated.
    else:
      return m

  @staticmethod
  def step_started(line):
    return line.startswith('@@@STEP_STARTED@@@')

  @staticmethod
  def step_closed(line):
    return line.startswith('@@@STEP_CLOSED@@@')

  @staticmethod
  def step_warnings(line):
    return (line.startswith('@@@STEP_WARNINGS@@@') or
            line.startswith('@@@BUILD_WARNINGS@@@'))  # Deprecated.

  @staticmethod
  def step_failure(line):
    return (line.startswith('@@@STEP_FAILURE@@@') or
            line.startswith('@@@BUILD_FAILED@@@'))  # Deprecated.

  @staticmethod
  def step_exception(line):
    return (line.startswith('@@@STEP_EXCEPTION@@@') or
            line.startswith('@@@BUILD_EXCEPTION@@@'))  # Deprecated.

  @staticmethod
  def halt_on_failure(line):
    return line.startswith('@@@HALT_ON_FAILURE@@@')

  @staticmethod
  def honor_zero_return_code(line):
    return line.startswith('@@@HONOR_ZERO_RETURN_CODE@@@')

  @staticmethod
  def step_clear(line):
    return line.startswith('@@@STEP_CLEAR@@@')

  @staticmethod
  def step_summary_clear(line):
    return line.startswith('@@@STEP_SUMMARY_CLEAR@@@')

  @staticmethod
  def step_text(line):
    return Match._parse_line('^@@@STEP_TEXT@(.*)@@@', line)

  @staticmethod
  def step_summary_text(line):
    return Match._parse_line('^@@@STEP_SUMMARY_TEXT@(.*)@@@', line)

  @staticmethod
  def seed_step(line):
    return Match._parse_line('^@@@SEED_STEP (.*)@@@', line)

  @staticmethod
  def step_cursor(line):
    return Match._parse_line('^@@@STEP_CURSOR (.*)@@@', line)

  @staticmethod
  def build_step(line):
    return Match._parse_line('^@@@BUILD_STEP (.*)@@@', line)


def _merge_envs(original, override):
  result = original.copy()
  if not override:
    return result
  for k, v in override.items():
    if v is None:
      if k in result:
        del result[k]
    else:
      result[k] = v
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


def _run_step(stream, build_failure,
              name, cmd, cwd=None, env=None,
              skip=False, always_run=False,
              ignore_annotations=False,
              **kwargs):
  """Runs a single step.

  Context:
    stream: StructuredAnnotationStream to use to emit step
    build_failure: True if some previous step has failed

  Step parameters:
    name: name of the step, will appear in buildbots waterfall
    cmd: command to run, list of one or more strings
    cwd: absolute path to working directory for the command
    env: dict with overrides for environment variables
    skip: True to skip this step
    always_run: True to run the step even if some previous step failed
    ignore_annotations: if True will ignore annotations emitted by the step

  Returns new value for build_failure.
  """
  if skip or (build_failure and not always_run):
    return build_failure, None

  # For error reporting.
  step_dict = locals().copy()
  step_dict.pop('stream')
  step_dict.update(kwargs)

  filter_obj = None
  if ignore_annotations:
    class AnnotationFilter(chromium_utils.RunCommandFilter):
      def FilterLine(self, line):
        return line.replace('@@@', '###')
    filter_obj = AnnotationFilter()

  ret = None
  try:
    with stream.step(name) as s:
      ret = chromium_utils.RunCommand(command=map(str, cmd),
                                      cwd=cwd,
                                      env=_merge_envs(os.environ, env),
                                      filter_obj=filter_obj)
      if ret != 0:
        print 'step returned non-zero exit code: %d' % ret
        print 'step was: %s' % json.dumps(step_dict)
        s.step_failure()
        build_failure = True
  except OSError:
    # File wasn't found, error has been already reported to stream.
    build_failure = True

  return build_failure, ret


def run_steps(steps, build_failure):
  for step in steps:
    error = _validate_step(step)
    if error:
      print 'Invalid step - %s\n%s' % (error, json.dumps(step, indent=2))
      sys.exit(1)

  seed_steps = []
  for step in steps:
    seed_steps.append(step['name'])
    seed_steps.extend(step.get('seed_steps', []))

  stream = StructuredAnnotationStream(seed_steps=seed_steps)
  ret_codes = []
  for step in steps:
    build_failure, ret = _run_step(stream, build_failure, **step)
    ret_codes.append(ret)
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

  if args[0] == '-':
    steps.extend(json.load(sys.stdin))
  else:
    with open(args[0], 'rb') as f:
      steps.extend(json.load(f))

  return 1 if run_steps(steps, False)[0] else 0


if __name__ == '__main__':
  sys.exit(main())
