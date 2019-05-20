# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

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
import re
import shutil
import signal
import sys
import tempfile
import traceback

import coverage

from google.protobuf import json_format

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

# pylint: disable=import-error
from PB.recipe_engine.internal.test.test_result import TestResult

from .... import config_types

from ...test import magic_check_fn
from ...test.execute_test_case import execute_test_case

from ..doc.cmd import regenerate_docs

from .common import DiffFailure, CheckFailure, BadTestFailure, CrashFailure
from .common import TestDescription, TestResult_


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
_MODE_TEST, _MODE_TRAIN = range(2)


# Allow regex patterns to be 'deep copied' by using them as-is.
# pylint: disable=protected-access
copy._deepcopy_dispatch[re._pattern_type] = copy._deepcopy_atomic


@contextlib.contextmanager
def coverage_context(include=None):
  """Context manager that records coverage data."""
  c = coverage.coverage(config_file=False, include=include)

  # Sometimes our strict include lists will result in a run
  # not adding any coverage info. That's okay, avoid output spam.
  c._warn_no_data = False

  c.start()
  try:
    yield c
  finally:
    c.stop()


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


def run_test(train_mode, test_description):
  """Runs a test. Returns TestResults object."""
  expected = None
  if os.path.exists(test_description.expectation_path):
    try:
      with open(test_description.expectation_path) as fil:
        expected = fil.read()
    except Exception:
      if train_mode:
        # Ignore errors when training; we're going to overwrite the file anyway.
        expected = None
      else:
        raise

  main_repo = _RECIPE_DEPS.main_repo
  break_funcs = [
    main_repo.recipes[test_description.recipe_name].global_symbols['RunSteps'],
  ]

  (
    actual_obj, failed_checks, crash_failure, bad_test_failures, coverage_data
  ) = run_recipe(
      test_description.recipe_name, test_description.test_name,
      test_description.covers)

  failures = []

  status = _compare_results(
      train_mode, failures, actual_obj, expected,
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

  return TestResult_(test_description, failures, coverage_data,
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
  main_repo_root = 'RECIPE_REPO[%s]' % recipe_deps.main_repo.name

  # Derive path to python prefix. We WOULD use `sys.prefix` and
  # `sys.real_prefix` (a vpython construction), however SOME python
  # distributions have these set to unhelpful paths (like '/usr'). So, we import
  # one library known to be in the vpython prefix and one known to be in the
  # system prefix and then derive the real paths from those.
  #
  # FIXME(iannucci): This is all pretty fragile.
  dirn = os.path.dirname
  # os is in the vpython root
  roots[os.path.abspath(dirn(dirn(dirn(os.__file__))))] = 'PYTHON'
  # io is in the system root
  import io
  roots[os.path.abspath(dirn(dirn(dirn(io.__file__))))] = 'PYTHON'
  # coverage is in the local site-packages in the vpython root
  roots[os.path.abspath(dirn(dirn(coverage.__file__)))] = \
      'PYTHON(site-packages)'

  def _root_subber(match):
    root = roots[match.group(1)]
    path = match.group(2).replace('\\', '/')
    line = ', line ' + match.group(3)
    # If this is a path from some other repo, then replace the line number as
    # it is very noisy, but the general shape of the traceback can still be
    # useful.
    if root != main_repo_root:
      line = ''
    return '"%s%s"%s' % (root, path, line)

  # Replace paths from longest to shortest; because of the way the recipe engine
  # fetches dependencies (i.e. into the .recipe_deps folder) dependencies of
  # repo X will have a prefix of X's path.
  paths = sorted(roots.keys(), key=lambda v: -len(v))

  # Look for paths in double quotes (as we might see in a stack trace)
  replacer = re.compile(r'"(%s)([^"]*)", line (\d+)' % ('|'.join(map(re.escape, paths)),))

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


def run_recipe(recipe_name, test_name, covers):
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

  with coverage_context(include=covers) as cov:
    result, steps_ran, buffered_steps = execute_test_case(
        _RECIPE_DEPS, recipe_name, test_data)

  coverage_data = cov.get_data()

  raw_expectations = _merge_presentation_updates(steps_ran, buffered_steps)

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
  with coverage_context(include=covers) as cov:
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
        recipe_tests = list(recipe.gen_tests())  # run generator

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


def run_worker(train_mode, test):
  """Worker for 'run' command (note decorator above)."""
  with scoped_override(os, '_exit', sys.exit):
    try:
      if _KILL_SWITCH.is_set():
        return (False, test, 'kill switch')
      return (True, test, run_test(train_mode, test))
    except:  # pylint: disable=bare-except
      return (False, test, traceback.format_exc())


def run_train(gen_docs, test_filter, jobs, json_file):
  rc = run_run(test_filter, jobs, json_file, train_mode=True)
  if rc == 0 and gen_docs:
    print('Generating README.recipes.md')
    regenerate_docs(_RECIPE_DEPS.main_repo)
  return rc


def run_run(test_filter, jobs, json_file, train_mode):
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

  with kill_switch():
    pool = multiprocessing.Pool(jobs)
    results = pool.map(functools.partial(run_worker, train_mode), tests)

  print()

  used_expectations = set()

  for success, test_description, details in results:
    if success:
      assert isinstance(details, TestResult_)
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
      if train_mode:
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

  if args.subcommand == 'run':
    return run_run(args.test_filters, args.jobs, args.json, train_mode=False)
  if args.subcommand == 'train':
    return run_train(args.docs, args.test_filters, args.jobs, args.json)

  raise ValueError('Unknown subcommand %r' % (args.subcommand,))
