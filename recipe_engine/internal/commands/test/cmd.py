# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import bdb
import collections
import contextlib
import copy
import cStringIO
import datetime
import difflib
import errno
import fnmatch
import functools
import json
import multiprocessing
import os
import pdb
import re
import shutil
import signal
import sys
import tempfile
import traceback

import coverage

from google.protobuf import json_format

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

from PB.recipe_engine.test_result import TestResult

from .... import config_types

from ...engine import RecipeEngine
from ...engine_env import FakeEnviron
from ...exceptions import CrashEngine
from ...step_runner.sim import SimulationStepRunner
from ...stream import StreamEngine
from ...stream.annotator import AnnotatorStreamEngine
from ...stream.invariants import StreamEngineInvariants
from ...test import magic_check_fn

from ..doc.cmd import regenerate_docs


# These variables must be set in the dynamic scope of the functions in this
# file.  We do this instead of passing because they're not picklable, and
# that's required by multiprocessing.
#
# For type hinting we populate this with an empty RecipeDeps, but it's
# overwritten in main().
# pylint: disable=global-statement
_RECIPE_DEPS = None # type: recipe_deps.RecipeDeps

# A function which efficiently scrubs system-specific paths from tracebacks. Set
# in main().
_PATH_CLEANER = None


# An event to signal exit, for example on Ctrl-C.
_KILL_SWITCH = multiprocessing.Event()


# This maps from (recipe_name,test_name) -> yielded test_data. It's outside of
# run_recipe so that it can persist between RunRecipe calls in the same process.
_GEN_TEST_CACHE = {}

# These are modes that various functions in this file switch on.
_MODE_TEST, _MODE_TRAIN, _MODE_DEBUG = range(3)


# Allow regex patterns to be 'deep copied' by using them as-is.
# pylint: disable=protected-access
copy._deepcopy_dispatch[re._pattern_type] = copy._deepcopy_atomic


@contextlib.contextmanager
def coverage_context(include=None, enable=True):
  """Context manager that records coverage data."""
  c = coverage.coverage(config_file=False, include=include)

  if not enable:
    yield c
    return

  # Sometimes our strict include lists will result in a run
  # not adding any coverage info. That's okay, avoid output spam.
  c._warn_no_data = False

  c.start()
  try:
    yield c
  finally:
    c.stop()


class TestFailure(object):
  """Base class for different kinds of test failures."""

  def format(self):
    """Returns a human-readable description of the failure."""
    raise NotImplementedError()

  def as_proto(self):
    """Returns a machine-readable description of the failure as proto.

    The returned message should be an instance of TestResult.TestFailure
    (see test_result.proto).
    """
    raise NotImplementedError()


class DiffFailure(TestFailure):
  """Failure when simulated recipe commands don't match recorded expectations.
  """

  def __init__(self, diff):
    self.diff = diff

  def format(self):
    return self.diff

  def as_proto(self):
    proto = TestResult.TestFailure()
    proto.diff_failure.MergeFrom(TestResult.DiffFailure())
    return proto


class CheckFailure(TestFailure):
  """Failure when any of the post-process checks fails."""

  def __init__(self, check):
    self.check = check

  def format(self):
    return self.check.format(indent=4)

  def as_proto(self):
    return self.check.as_proto()


class BadTestFailure(TestFailure):
  """Failure when the test itself was bad somehow (e.g. provides mock data
  for steps which never ran)."""

  def __init__(self, error):
    self.error = error

  def format(self):
    return str(self.error)

  def as_proto(self):
    proto = TestResult.TestFailure()
    proto.bad_test_failure.error = self.error
    return proto


class CrashFailure(TestFailure):
  """Failure when the recipe run crashes with an uncaught exception."""

  def __init__(self, error):
    self.error = error

  def format(self):
    return str(self.error)

  def as_proto(self):
    proto = TestResult.TestFailure()
    proto.crash_failure.error = self.error
    return proto


class _TestResult(object):
  """Result of running a test."""

  def __init__(self, test_description, failures, coverage_data,
               generates_expectation):
    self.test_description = test_description
    self.failures = failures
    self.coverage_data = coverage_data
    self.generates_expectation = generates_expectation


class TestDescription(object):
  """Identifies a specific test.

  Deliberately small and picklable for use with multiprocessing."""

  def __init__(self, recipe_name, test_name, expect_dir, covers):
    self.recipe_name = recipe_name
    self.test_name = test_name
    self.expect_dir = expect_dir
    self.covers = covers

  @staticmethod
  def filesystem_safe(name):
    return ''.join('_' if c in '<>:"\\/|?*\0' else c for c in name)

  @property
  def full_name(self):
    return '%s.%s' % (self.recipe_name, self.test_name)

  @property
  def expectation_path(self):
    name = self.filesystem_safe(self.test_name)
    return os.path.join(self.expect_dir, name + '.json')


@contextlib.contextmanager
def maybe_debug(break_funcs, enable):
  """Context manager to wrap a block to possibly run under debugger.

  Arguments:
    break_funcs(list): functions to set up breakpoints for
    enable(bool): whether to actually trigger debugger, or be no-op
  """
  if not enable:
    yield
    return

  debugger = pdb.Pdb()

  for func in break_funcs:
    debugger.set_break(
        func.func_code.co_filename,
        func.func_code.co_firstlineno,
        funcname=func.func_code.co_name)

  try:
    def dispatch_thunk(*args):
      """Triggers 'continue' command when debugger starts."""
      val = debugger.trace_dispatch(*args)
      debugger.set_continue()
      sys.settrace(debugger.trace_dispatch)
      return val
    debugger.reset()
    sys.settrace(dispatch_thunk)
    try:
      yield
    finally:
      debugger.quitting = 1
      sys.settrace(None)
  except bdb.BdbQuit:
    pass
  except Exception:
    traceback.print_exc()
    print('Uncaught exception. Entering post mortem debugging')
    print('Running \'cont\' or \'step\' will restart the program')
    t = sys.exc_info()[2]
    debugger.interaction(None, t)


def _compare_results(train_mode, failures, actual_obj, expected,
                    expectation_path):
  """Compares the actual and expected results.

  Args:

    * train_mode (bool) - if we're in _MODE_TRAIN
    * failures (List[TestFailure]) - The list of accumulated failures for this
      test run. This function may append to this list.
    * actual_obj (Jsonish test expectation) - What the simulation actually
      produced.
    * expected (None|JSON encoded test expectation) - The current test
      expectation from the disk.
    * expectation_path (str) - The path on disk of the expectation file.

  Side-effects: appends to `failures` if something doesn't match up.
  Returns the character code for stdout.
  """
  if actual_obj is None and expected is None:
    return '.'

  actual = json.dumps(
      re_encode(actual_obj), sort_keys=True, indent=2,
      separators=(',', ': '))

  if actual == expected:
    return '.'

  if actual_obj is not None:
    if train_mode:
      expectation_dir = os.path.dirname(expectation_path)
      # This may race with other processes, so just attempt to create dir
      # and ignore failure if it already exists.
      try:
        os.makedirs(expectation_dir)
      except OSError as ex:
        if ex.errno != errno.EEXIST:
          raise ex
      with open(expectation_path, 'wb') as fil:
        fil.write(actual)
    else:
      diff = '\n'.join(difflib.unified_diff(
          unicode(expected).splitlines(),
          unicode(actual).splitlines(),
          fromfile='expected', tofile='actual',
          n=4, lineterm=''))

      failures.append(DiffFailure(diff))

  return 'D' if train_mode else 'F'


def run_test(test_description, mode):
  """Runs a test. Returns TestResults object."""
  expected = None
  if os.path.exists(test_description.expectation_path):
    try:
      with open(test_description.expectation_path) as fil:
        expected = fil.read()
    except Exception:
      if mode == _MODE_TRAIN:
        # Ignore errors when training; we're going to overwrite the file anyway.
        expected = None
      else:
        raise

  main_repo = _RECIPE_DEPS.main_repo
  break_funcs = [
    main_repo.recipes[test_description.recipe_name].global_symbols['RunSteps'],
  ]

  with maybe_debug(break_funcs, mode == _MODE_DEBUG):
    (
      actual_obj, failed_checks, crash_failure, bad_test_failures, coverage_data
    ) = run_recipe(
        test_description.recipe_name, test_description.test_name,
        test_description.covers,
        enable_coverage=(mode != _MODE_DEBUG))

  failures = []

  status = _compare_results(
      mode == _MODE_TRAIN, failures, actual_obj, expected,
      test_description.expectation_path)
  if bad_test_failures:
    status = 'B'
    failures.extend(bad_test_failures)
  if crash_failure:
    status = 'E'
    failures.append(crash_failure)
  if failed_checks:
    status = 'C'
    failures.extend([CheckFailure(c) for c in failed_checks])

  sys.stdout.write(status)
  sys.stdout.flush()

  return _TestResult(test_description, failures, coverage_data,
                    actual_obj is not None)


def _make_path_cleaner(recipe_deps):
  """Returns a filtering function which substitutes real paths-on-disk with
  expectation-compatible `RECIPE_REPO[repo name]` mock paths. This only works
  for paths contained in double-quotes (e.g. as part of a stack trace).

  Args:

    * recipe_deps (RecipeDeps) - All of the loaded recipe dependencies.

  Returns `func(lines : List[str]) -> List[str]` which converts real on-disk
  absolute paths to RECIPE_REPO mock paths.
  """
  # maps path_to_replace -> replacement
  roots = {}
  # paths of all recipe_deps
  for repo in recipe_deps.repos.itervalues():
    roots[repo.path] = 'RECIPE_REPO[%s]' % repo.name

  # NOTE: Recipes ALWAYS run under vpython currently, so unguarded access to
  # `sys.real_prefix` below is safe.
  # sys.prefix -> path of virtualenv prefix
  # sys.real_prefix -> path of system prefix
  roots[os.path.abspath(sys.prefix)] = 'PYTHON'
  roots[os.path.abspath(sys.real_prefix)] = 'PYTHON' # pylint: disable=no-member

  def _root_subber(match):
    return '"%s%s"' % (
      roots[match.group(1)], match.group(2).replace('\\', '/'))

  # Replace paths from longest to shortest; because of the way the recipe engine
  # fetches dependencies (i.e. into the .recipe_deps folder) dependencies of
  # repo X will have a prefix of X's path.
  paths = sorted(roots.keys(), key=lambda v: -len(v))

  # Look for paths in double quotes (as we might see in a stack trace)
  replacer = re.compile(r'"(%s)([^"]*)"' % ('|'.join(map(re.escape, paths)),))

  return lambda lines: [replacer.sub(_root_subber, line) for line in lines]


def _merge_presentation_updates(steps_ran, presentation_steps):
  """Merges the steps ran (from the SimulationStepRunner) with the steps
  presented (from the SimulationAnnotatorStreamEngine).

  Args:

    * steps_ran (Dict[str, dict]) - Mapping of step name to its run details as
      an expectation dict (e.g. 'cmd', 'env', etc.)
    * presentation_steps (OrderedDict[str, StringIO]) - Mapping of presentation
      step name (in the order that they were presented) to all emitted
      annotations for that step.

  Returns OrderedDict[str, expectation: dict]. This will have the order of steps
  in the order that they were presented.
  """
  ret = collections.OrderedDict()
  for step_name, step_presented in presentation_steps.iteritems():
    # root annotations
    if step_name is None:
      continue
    ret[step_name] = steps_ran.get(step_name, {
      'name': step_name,
      # TODO(iannucci): Drop 'cmd' field for presentation-only steps.
      'cmd': [],
    })
    output = step_presented.getvalue()
    if output:
      lines = _PATH_CLEANER(output.splitlines())
      # wowo hacks!
      # We only want to see $debug if it's got a crash in it.
      if "@@@STEP_LOG_LINE@$debug@Unhandled exception:@@@" not in lines:
        lines = [line for line in lines if '$debug' not in line]
      if lines:
        ret[step_name]['~followup_annotations'] = lines

  return ret


def _check_exception(expected_exception, raw_expectations):
  """Check to see if the test run failed with an exception from RunSteps.

  This currently extracts and does some lite parsing of the stacktrace from the
  "RECIPE CRASH (Uncaught exception)" step, which the engine produces from
  _log_crash when RunSteps tosses a non StepFailure exception. This is
  definitely looser than it should be, but it's the best we can do until
  expectations are natively object-oriented instead of bag of JSONish stuff.
  That said, it works Alright For Now (tm).

  Args:

    * expected_exception (str|None) - The name of the exception that the test
      case expected.
    * raw_expectations (Dict[str, dict]) - Mapping of presentation step name to
      the expectation dictionary for that step.

  Returns CrashFailure|None.
  """


  # Check to see if the user expected the recipe to crash in this test case or
  # not.
  # TODO(iannucci): This step name matching business is a bit sketchy.
  crash_step = raw_expectations.get('RECIPE CRASH (Uncaught exception)')
  crash_lines = crash_step['~followup_annotations'] if crash_step else []
  if expected_exception:
    if crash_step:
      # TODO(iannucci): the traceback really isn't "followup_annotations", but
      # stdout printed to the step currently ends up there. Fix this when
      # refactoring the test expectation format.
      #
      # The Traceback looks like:
      #   Traceback (most recent call last)
      #      ...
      #      ...
      #   ExceptionClass: Some exception text    <- want this line
      #   with newlines in it.
      exception_line = None
      for line in reversed(crash_lines):
        if line.startswith((' ', 'Traceback (most recent')):
          break
        exception_line = line
      # We expect the traceback line to look like:
      #   "ExceptionClass"
      #   "ExceptionClass: Text from the exception message."
      if not exception_line.startswith(expected_exception):
        return CrashFailure((
          'Expected exception mismatch in RunSteps. The test expected %r'
          ' but the exception line was %r.' % (
            expected_exception, exception_line,
          )
        ))
    else:
      return CrashFailure(
          'Missing expected exception in RunSteps. `api.expect_exception` is'
          ' specified, but the exception did not occur.'
      )
  else:
    if crash_step:
      msg_lines = [
        'Unexpected exception in RunSteps. Use `api.expect_exception` if'
        ' the crash is intentional.',
      ]

      traceback_idx = 0
      for i, line in enumerate(crash_lines):
        if line.startswith('Traceback '):
          traceback_idx = i
          break
      msg_lines.extend(
          '    ' + line
          for line in crash_lines[traceback_idx:]
          if not line.startswith('@@@')
      )
      return CrashFailure('\n'.join(msg_lines))

  return None


def _check_bad_test(test_data, steps_ran, presentation_steps):
  """Check to see if the user-provided test was malformed in some way.

  Currently this only identifies issues around unconsumed or misplaced
  step_data.

  Args:

    * test_data (recipe_engine.recipe_test_api.TestData) - The user-provided
      test data object, after running the test. We're checking to see that it's
      empty now.
    * steps_ran (List[str]) - The list of step names which the
      SimulationStepRunner saw. This will only include step names run via
      `api.step()`, and notably omits 'presentation only' steps such as parent
      nest steps or steps emitted by the engine for UI purposes (e.g. crash
      reports).
    * presentation_steps (List[str]) - The list of step names which the
      SimulationAnnotatorStreamEngine saw. This is the full list of steps which
      would occur on the build UI.

  Returns List[BadTestFailure].
  """
  ret = []

  for step in test_data.step_data:
    # This is an unconsumed step name.

    if step in presentation_steps:
      # If the step is unconsumed but present in presentation_steps it means
      # that the step was really a presentation-only step (like a parent nesting
      # step) and not eligble for test data.
      ret.append(BadTestFailure((
          'Mock data provided for presentation only step %r.\n'
          '  Presentation-only steps (like parent nesting steps) have no\n'
          '  subprocess associated with them and so cannot have mock data.\n'
          '  Please change your test so that it provides mock data for one of\n'
          '  the real steps.'
      ) % step))

    else:
      ret.append(BadTestFailure(
        'Mock data provided for non-existent step %r.' % step))

  if ret:
    ret.append(BadTestFailure(
        'For reference, this test ran the following steps:\n' +
        '\n'.join('  ' + repr(s) for s in steps_ran)
    ))

  return ret


def run_recipe(recipe_name, test_name, covers, enable_coverage=True):
  """Runs the recipe under test in simulation mode.

  # TODO(iannucci): Implement a better flow for this returned data; interaction
  # with run_test is a bit weird. Maybe combine/refactor them?

  Returns a tuple:
    - expectation data
    - failed post-process checks (if any)
    - a CrashFailure (if any)
    - a list of BadTestFailure objects (if any)
    - coverage data
  """
  config_types.ResetTostringFns()

  # Grab test data from the cache. This way it's only generated once.
  test_data = _GEN_TEST_CACHE[(recipe_name, test_name)]

  step_runner = SimulationStepRunner(test_data)
  annotator = SimulationAnnotatorStreamEngine()
  stream_engine = StreamEngineInvariants.wrap(annotator)

  props = test_data.properties.copy()
  props['recipe'] = recipe_name
  # Disable source manifest uploading by default.
  if '$recipe_engine/source_manifest' not in props:
    props['$recipe_engine/source_manifest'] = {}
  if 'debug_dir' not in props['$recipe_engine/source_manifest']:
    props['$recipe_engine/source_manifest']['debug_dir'] = None
  with coverage_context(include=covers, enable=enable_coverage) as cov:
    # run_steps shouldn't ever raise an exception (captured exceptions
    # are reported in expectations and then returned as part of 'result')
    environ = FakeEnviron()
    for key, value in test_data.environ.iteritems():
      environ[key] = value
    result = RecipeEngine.run_steps(
        _RECIPE_DEPS, props, stream_engine, step_runner, environ, '',
        test_data=test_data, skip_setup_build=True)

  coverage_data = cov.get_data()

  steps_ran = step_runner.export_steps_ran()

  raw_expectations = _merge_presentation_updates(
      steps_ran, annotator.buffered_steps)

  bad_test_failures = _check_bad_test(
      test_data, steps_ran.keys(), raw_expectations.keys())

  # Convert the result to a json object by dumping to json, and then parsing.
  raw_expectations['$result'] = json.loads(json_format.MessageToJson(
      result, including_default_value_fields=True))
  # Parse the jsonResult, so that it shows up nicely in expectations.
  if 'jsonResult' in raw_expectations['$result']:
    raw_expectations['$result']['jsonResult'] = json.loads(
        raw_expectations['$result']['jsonResult'])
  raw_expectations['$result']['name'] = '$result'

  crash_failure = _check_exception(
      test_data.expected_exception, raw_expectations)

  failed_checks = []
  with coverage_context(include=covers, enable=enable_coverage) as cov:
    result_data, failed_checks = magic_check_fn.post_process(
        raw_expectations, test_data)
  coverage_data.update(cov.get_data())

  return (
    result_data, failed_checks, crash_failure, bad_test_failures, coverage_data
  )


def get_tests(test_filter=None):
  """Returns a list of tests for current recipe repo."""
  tests = []
  coverage_data = coverage.CoverageData()

  main_repo = _RECIPE_DEPS.main_repo
  mods_base_path = os.path.join(main_repo.recipes_root_path, 'recipe_modules')

  all_modules = set(main_repo.modules.keys())
  covered_modules = set()

  base_covers = []

  coverage_include = os.path.join(mods_base_path, '*', '*.py')
  for module_name in all_modules:
    module = main_repo.modules[module_name]

    # Import module under coverage context. This ensures we collect
    # coverage of all definitions and globals.
    with coverage_context(include=coverage_include) as cov:
      imported_module = module.do_import()
    coverage_data.update(cov.get_data())

    # Recipe modules can only be covered by tests inside the same module.
    # To make transition possible for existing code (which will require
    # writing tests), a temporary escape hatch is added.
    # TODO(phajdan.jr): remove DISABLE_STRICT_COVERAGE (crbug/693058).
    if imported_module.DISABLE_STRICT_COVERAGE:
      covered_modules.add(module_name)
      # Make sure disabling strict coverage also disables our additional check
      # for module coverage. Note that coverage will still raise an error if
      # the module is executed by any of the tests, but having less than 100%
      # coverage.
      base_covers.append(os.path.join(module.path, '*.py'))

  recipe_filter = []
  if test_filter:
    recipe_filter = [p.split('.', 1)[0] for p in test_filter]
  for recipe in main_repo.recipes.itervalues():
    if recipe_filter:
      match = False
      for pattern in recipe_filter:
        if fnmatch.fnmatch(recipe.name, pattern):
          match = True
          break
      if not match:
        continue

    try:
      covers = [recipe.path] + base_covers

      # Example/test recipes in a module always cover that module.
      if recipe.module:
        covered_modules.add(recipe.module.name)
        covers.append(os.path.join(recipe.module.path, '*.py'))

      with coverage_context(include=covers) as cov:
        recipe_tests = recipe.gen_tests()

      coverage_data.update(cov.get_data())
      # TODO(iannucci): move expectation tree outside of the recipe tree.
      expect_dir = os.path.splitext(recipe.path)[0] + '.expected'

      for test_data in recipe_tests:
        # Put the test data in shared cache. This way it can only be generated
        # once. We do this primarily for _correctness_ , for example in case
        # a weird recipe generates tests non-deterministically. The recipe
        # engine should be robust against such user recipe code where
        # reasonable.
        key = (recipe.name, test_data.name)
        if key in _GEN_TEST_CACHE:
          raise ValueError('Duplicate test found: %s' % test_data.name)
        _GEN_TEST_CACHE[key] = copy.deepcopy(test_data)

        test_description = TestDescription(
            recipe.name, test_data.name, expect_dir, covers)
        if test_filter:
          for pattern in test_filter:
            if fnmatch.fnmatch(test_description.full_name, pattern):
              tests.append(test_description)
              break
        else:
          tests.append(test_description)
    except:
      info = sys.exc_info()
      new_exec = Exception('While generating results for %r: %s: %s' % (
        recipe.name, info[0].__name__, str(info[1])))
      raise new_exec.__class__, new_exec, info[2]

  uncovered_modules = sorted(all_modules.difference(covered_modules))
  return (tests, coverage_data, uncovered_modules)


def run_list(json_file):
  """Implementation of the 'list' command."""
  tests, _coverage_data, _uncovered_modules = get_tests()
  result = sorted(t.full_name for t in tests)
  if json_file:
    json.dump({
        'format': 1,
        'tests': result,
    }, json_file)
  else:
    print('\n'.join(result))
  return 0


def run_diff(baseline, actual, json_file=None):
  """Implementation of the 'diff' command."""
  baseline_proto = TestResult()
  json_format.ParseDict(json.load(baseline), baseline_proto)

  actual_proto = TestResult()
  json_format.ParseDict(json.load(actual), actual_proto)

  success, results_proto = _diff_internal(baseline_proto, actual_proto)

  if json_file:
    obj = json_format.MessageToDict(
        results_proto, preserving_proto_field_name=True)
    json.dump(obj, json_file)

  return 0 if success else 1

def _diff_internal(baseline_proto, actual_proto):
  results_proto = TestResult(version=1, valid=True)

  if (not baseline_proto.valid or
      not actual_proto.valid or
      baseline_proto.version != 1 or
      actual_proto.version != 1):
    results_proto.valid = False
    return (False, results_proto)

  success = True

  for filename, details in actual_proto.coverage_failures.iteritems():
    actual_uncovered_lines = set(details.uncovered_lines)
    baseline_uncovered_lines = set(
        baseline_proto.coverage_failures[filename].uncovered_lines)
    cover_diff = actual_uncovered_lines.difference(baseline_uncovered_lines)
    if cover_diff:
      success = False
      results_proto.coverage_failures[
          filename].uncovered_lines.extend(cover_diff)

  for test_name, test_failures in actual_proto.test_failures.iteritems():
    for test_failure in test_failures.failures:
      found = False
      for baseline_test_failure in baseline_proto.test_failures[
          test_name].failures:
        if test_failure == baseline_test_failure:
          found = True
          break
      if not found:
        success = False
        results_proto.test_failures[test_name].failures.extend([test_failure])

  actual_uncovered_modules = set(actual_proto.uncovered_modules)
  baseline_uncovered_modules = set(baseline_proto.uncovered_modules)
  uncovered_modules_diff = actual_uncovered_modules.difference(
      baseline_uncovered_modules)
  if uncovered_modules_diff:
    success = False
    results_proto.uncovered_modules.extend(uncovered_modules_diff)

  actual_unused_expectations = set(actual_proto.unused_expectations)
  baseline_unused_expectations = set(baseline_proto.unused_expectations)
  unused_expectations_diff = actual_unused_expectations.difference(
      baseline_unused_expectations)
  if unused_expectations_diff:
    success = False
    results_proto.unused_expectations.extend(unused_expectations_diff)

  return (success, results_proto)


def cover_omit():
  """Returns list of patterns to omit from coverage analysis."""
  omit = [ ]

  mod_dir_base = os.path.join(
    _RECIPE_DEPS.main_repo.recipes_root_path,
    'recipe_modules')
  if os.path.isdir(mod_dir_base):
      omit.append(os.path.join(mod_dir_base, '*', 'resources', '*'))

  # Exclude recipe engine files from simulation test coverage. Simulation tests
  # should cover "user space" recipe code (recipes and modules), not the engine.
  # The engine is covered by unit tests, not simulation tests.
  omit.append(os.path.join(RECIPE_ENGINE_PATH[0], '*'))

  return omit


@contextlib.contextmanager
def scoped_override(obj, attr, override):
  """Sets |obj|.|attr| to |override| in scope of the context manager."""
  orig = getattr(obj, attr)
  setattr(obj, attr, override)
  yield
  setattr(obj, attr, orig)


def worker(f):
  """Wrapper for a multiprocessing worker function.

  This addresses known issues with multiprocessing workers:

    - they can hang on uncaught exceptions
    - os._exit causes hangs, so we patch it
    - we need explicit kill switch to clearly terminate parent"""
  @functools.wraps(f)
  def wrapper(test, *args, **kwargs):
    with scoped_override(os, '_exit', sys.exit):
      try:
        if _KILL_SWITCH.is_set():
          return (False, test, 'kill switch')
        return (True, test, f(test, *args, **kwargs))
      except:  # pylint: disable=bare-except
        return (False, test, traceback.format_exc())
  return wrapper


@worker
def run_worker(test, mode):
  """Worker for 'run' command (note decorator above)."""
  return run_test(test, mode)


def run_train(gen_docs, test_filter, jobs, json_file):
  rc = run_run(test_filter, jobs, json_file, _MODE_TRAIN)
  if rc == 0 and gen_docs:
    print('Generating README.recipes.md')
    regenerate_docs(_RECIPE_DEPS.main_repo)
  return rc


def run_run(test_filter, jobs, json_file, mode):
  """Implementation of the 'run' command."""
  start_time = datetime.datetime.now()

  rc = 0
  results_proto = TestResult()
  results_proto.version = 1
  results_proto.valid = True

  tests, coverage_data, uncovered_modules = get_tests(test_filter)
  if uncovered_modules and not test_filter:
    rc = 1
    results_proto.uncovered_modules.extend(uncovered_modules)
    print('ERROR: The following modules lack test coverage: %s' % (
        ','.join(uncovered_modules)))

  if mode == _MODE_DEBUG:
    results = []
    for t in tests:
      results.append(run_worker(t, mode))
  else:
    with kill_switch():
      pool = multiprocessing.Pool(jobs)
      # the 'mode=mode' is necessary, because we want a function call like:
      #   func(test) -> run_worker(test, mode)
      # if we supply 'mode' as an arg, it will end up calling:
      #   func(test) -> run_worker(mode, test)
      results = pool.map(functools.partial(run_worker, mode=mode), tests)

  print()

  used_expectations = set()

  for success, test_description, details in results:
    if success:
      assert isinstance(details, _TestResult)
      if details.failures:
        rc = 1
        key = details.test_description.full_name
        print('%s failed:' % key)
        for failure in details.failures:
          results_proto.test_failures[key].failures.extend([failure.as_proto()])
          print(failure.format())
      coverage_data.update(details.coverage_data)
      if details.generates_expectation:
        used_expectations.add(details.test_description.expectation_path)
        used_expectations.add(
            os.path.dirname(details.test_description.expectation_path))
    else:
      rc = 1
      results_proto.valid = False
      failure_proto = TestResult.TestFailure()
      failure_proto.internal_failure.MergeFrom(TestResult.InternalFailure())
      results_proto.test_failures[test_description.full_name].failures.extend([
          failure_proto])
      print('%s failed:' % test_description.full_name)
      print(details)

  if test_filter:
    print('NOTE: not checking coverage, because a filter is enabled')
  else:
    try:
      # TODO(phajdan.jr): Add API to coverage to load data from memory.
      with tempfile.NamedTemporaryFile(delete=False) as coverage_file:
        coverage_data.write_file(coverage_file.name)

      cov = coverage.coverage(
          data_file=coverage_file.name, config_file=False, omit=cover_omit())
      cov.load()

      # TODO(phajdan.jr): Add API to coverage to apply path filters.
      reporter = coverage.report.Reporter(cov, cov.config)
      file_reporters = reporter.find_file_reporters(
          coverage_data.measured_files())

      # TODO(phajdan.jr): Make coverage not throw CoverageException for no data.
      if file_reporters:
        outf = cStringIO.StringIO()
        percentage = cov.report(file=outf, show_missing=True, skip_covered=True)
        if int(percentage) != 100:
          rc = 1
          print(outf.getvalue())
          print('FATAL: Insufficient coverage (%.f%%)' % int(percentage))

          for fr in file_reporters:
            _fname, _stmts, _excl, missing, _mf = cov.analysis2(fr.filename)
            if missing:
              results_proto.coverage_failures[
                  fr.filename].uncovered_lines.extend(missing)
    finally:
      os.unlink(coverage_file.name)

  if test_filter:
    print('NOTE: not checking for unused expectations, '
          'because a filter is enabled')
  else:
    # Gather the paths for all expectations folders and files.
    actual_expectations = reduce(
      lambda s, r: s | r.expectation_paths,
      _RECIPE_DEPS.main_repo.recipes.itervalues(),
      set()
    )

    unused_expectations = sorted(actual_expectations - used_expectations)
    if unused_expectations:
      if mode == _MODE_TRAIN:
        # we only want to prune expectations if training was otherwise
        # successful. Otherwise a failure during training can blow away expected
        # directories which contain things like OWNERS files.
        if rc == 0:
          for entry in unused_expectations:
            if not os.path.exists(entry):
              continue
            if os.path.isdir(entry):
              shutil.rmtree(entry)
            else:
              os.unlink(entry)
      else:
        rc = 1
        results_proto.unused_expectations.extend(unused_expectations)
        print('FATAL: unused expectations found:')
        print('\n'.join(unused_expectations))

  finish_time = datetime.datetime.now()
  print('-' * 70)
  print('Ran %d tests in %0.3fs' % (
      len(tests), (finish_time - start_time).total_seconds()))
  print()
  print('OK' if rc == 0 else 'FAILED')

  if rc != 0:
    print()
    print('NOTE: You may need to re-train the expectation files by running:')
    print()
    new_args = [('train' if s == 'run' else s) for s in sys.argv]
    new_args[0] = os.path.relpath(new_args[0])
    if not new_args[0].startswith('.%s' % os.path.sep):
      new_args[0] = os.path.join('.', new_args[0])
    print('  ' + ' '.join(new_args))
    print()
    print('This will update all the .json files to have content which matches')
    print('the current recipe logic. Review them for correctness and include')
    print('them with your CL.')

  if json_file:
    obj = json_format.MessageToDict(
        results_proto, preserving_proto_field_name=True)
    json.dump(obj, json_file)

  return rc


class _NopFile(object):
  # pylint: disable=multiple-statements,missing-docstring
  def write(self, data): pass
  def flush(self): pass


class _NopLogStream(StreamEngine.Stream):
  # pylint: disable=multiple-statements
  def write_line(self, line): pass
  def close(self): pass


class _NopStepStream(AnnotatorStreamEngine.StepStream):
  def __init__(self, engine, step_name):
    super(_NopStepStream, self).__init__(engine, _NopFile(), step_name)

  def new_log_stream(self, _):
    return _NopLogStream()

  def close(self):
    pass


class _SimulationStepStream(AnnotatorStreamEngine.StepStream):
  # We override annotations we don't want to show up in followup_annotations
  def new_log_stream(self, log_name):
    # We sink 'execution details' to dev/null. This is the log that the recipe
    # engine produces that contains the printout of the command, environment,
    # etc.
    #
    # The '$debug' log is conditionally filtered in _merge_presentation_updates.
    if log_name in ('execution details',):
      return _NopLogStream()
    return super(_SimulationStepStream, self).new_log_stream(log_name)

  def trigger(self, spec):
    pass

  def close(self):
    pass


class SimulationAnnotatorStreamEngine(AnnotatorStreamEngine):
  """Stream engine which just records generated commands."""

  # TODO(iannucci): Move this (and related classes) to their own file, perhaps
  # adjacent to AnnotatorStreamEngine.

  def __init__(self):
    self._step_buffer_map = collections.OrderedDict()
    super(SimulationAnnotatorStreamEngine, self).__init__(
        self._step_buffer(None))

  @property
  def buffered_steps(self):
    """Returns an OrderedDict of all steps run by dot-name to a cStringIO
    buffer with any annotations printed."""
    return self._step_buffer_map

  def _step_buffer(self, step_name):
    return self._step_buffer_map.setdefault(step_name, cStringIO.StringIO())

  def new_step_stream(self, step_config):
    # TODO(iannucci): don't skip these. Omitting them for now to reduce the
    # amount of test expectation changes.
    steps_to_skip = (
      'recipe result',   # explicitly covered by '$result'
    )
    if step_config.name in steps_to_skip:
      return _NopStepStream(self, step_config.name)

    stream = _SimulationStepStream(
        self, self._step_buffer(step_config.name), step_config.name)
    # TODO(iannucci): this is duplicated with
    # AnnotatorStreamEngine._create_step_stream
    if len(step_config.name_tokens) > 1:
      # Emit our current nest level, if we are nested.
      stream.output_annotation(
          'STEP_NEST_LEVEL', str(len(step_config.name_tokens)-1))
    return stream


def handle_killswitch(*_):
  """Function invoked by ctrl-c. Signals worker processes to exit."""
  _KILL_SWITCH.set()

  # Reset the signal to DFL so that double ctrl-C kills us for sure.
  signal.signal(signal.SIGINT, signal.SIG_DFL)
  signal.signal(signal.SIGTERM, signal.SIG_DFL)


@contextlib.contextmanager
def kill_switch():
  """Context manager to handle ctrl-c properly with multiprocessing."""
  orig_sigint = signal.signal(signal.SIGINT, handle_killswitch)
  try:
    orig_sigterm = signal.signal(signal.SIGTERM, handle_killswitch)
    try:
      yield
    finally:
      signal.signal(signal.SIGTERM, orig_sigterm)
  finally:
    signal.signal(signal.SIGINT, orig_sigint)

  if _KILL_SWITCH.is_set():
    sys.exit(1)


# TODO(phajdan.jr): Consider integrating with json.JSONDecoder.
def re_encode(obj):
  """Ensure consistent encoding for common python data structures."""
  if isinstance(obj, (unicode, str)):
    if isinstance(obj, str):
      obj = obj.decode('utf-8', 'replace')
    return obj.encode('utf-8', 'replace')
  elif isinstance(obj, collections.Mapping):
    return {re_encode(k): re_encode(v) for k, v in obj.iteritems()}
  elif isinstance(obj, collections.Iterable):
    return [re_encode(i) for i in obj]
  else:
    return obj


def main(args):
  """Runs simulation tests on a given repo of recipes.

  Args:
    args: the parsed args (see add_subparser).
  Returns:
    Exit code
  """
  global _RECIPE_DEPS, _PATH_CLEANER
  _RECIPE_DEPS = args.recipe_deps
  _PATH_CLEANER = _make_path_cleaner(args.recipe_deps)

  if args.subcommand == 'list':
    return run_list(args.json)
  if args.subcommand == 'diff':
    return run_diff(args.baseline, args.actual, json_file=args.json)
  if args.subcommand == 'run':
    return run_run(args.filter, args.jobs, args.json, _MODE_TEST)
  if args.subcommand == 'train':
    return run_train(args.docs, args.filter, args.jobs, args.json)
  if args.subcommand == 'debug':
    return run_run(args.filter, None, None, _MODE_DEBUG)
  raise ValueError('Unknown subcommand %r' % (args.subcommand,))
