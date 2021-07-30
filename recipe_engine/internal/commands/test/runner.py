# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from builtins import str
from future.utils import iteritems, itervalues
from past.builtins import basestring

import collections
import difflib
import errno
import json
import multiprocessing
import os
import re
import sys
import tempfile
import traceback

import coverage

from gevent import subprocess
import gevent

from google.protobuf import json_format as jsonpb

from recipe_engine import __path__ as RECIPE_ENGINE_PATH
from recipe_engine.util import extract_tb, enable_filtered_stacks

# pylint: disable=import-error
import PB
from PB.recipe_engine.internal.test.runner import Description, Outcome

from ... import legacy

from .... import config_types
from .... import engine_types

from ...global_shutdown import GLOBAL_SHUTDOWN
from ...simple_cfg import RECIPES_CFG_LOCATION_REL
from ...test import magic_check_fn
from ...test.execute_test_case import execute_test_case

from .expectation_conversion import transform_exepctations
from .pipe import write_message, read_message


_PY2 = sys.version_info.major == 2


def _merge_presentation_updates(steps_ran, presentation_steps):
  """Merges the steps ran (from the SimulationStepRunner) with the steps
  presented (from the SimulationAnnotatorStreamEngine).

  Args:

    * steps_ran (Dict[str, dict]) - Mapping of step name to its run details as
      an expectation dict (e.g. 'cmd', 'env', etc.)
    * presentation_steps (OrderedDict[str, dict]) - Mapping of step name (in the
      order that they were presented) to a dict containing the collected
      annotations for that step.

  Returns OrderedDict[str, expectation: dict]. This will have the order of steps
  in the order that they were presented.
  """
  ret = collections.OrderedDict()
  for step_name, step_presented in iteritems(presentation_steps):
    # root annotations
    if step_name is None:
      continue
    ret[step_name] = steps_ran.get(step_name, {
      'name': step_name,
      # TODO(iannucci): Drop 'cmd' field for presentation-only steps.
      'cmd': [],
      'cost': None,
    })
    debug_logs = step_presented.get('logs', {}).get('$debug', None)
    # wowo hacks!
    # We only want to see $debug if it's got a crash in it.
    if debug_logs and 'Unhandled exception:' not in debug_logs.splitlines():
      step_presented['logs'].pop('$debug')

    ret[step_name].update(step_presented)

  return ret


def _check_bad_test(test_results, test_data, steps_ran, presentation_steps):
  """Check to see if the user-provided test was malformed in some way.

  Currently this only identifies issues around unconsumed or misplaced
  step_data.

  Args:

    * test_results (Outcome.Results) - The object to update in the event the
      test was bad.
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
  """
  for step in test_data.step_data:
    # This is an unconsumed step name.

    if step in presentation_steps:
      # If the step is unconsumed but present in presentation_steps it means
      # that the step was really a presentation-only step (like a parent nesting
      # step) and not eligble for test data.
      test_results.bad_test.extend([
        'Mock data provided for presentation only step %r.' % step,
        'Presentation-only steps (like parent nesting steps) have no',
        'subprocess associated with them and so cannot have mock data.',
        'Please change your test so that it provides mock data for one of',
        'the real steps.',
      ])

    else:
      test_results.bad_test.append(
          'Mock data provided for non-existent step %r.' % step)

  if test_results.bad_test:
    test_results.bad_test.extend([
        '',
        'For reference, this test ran the following steps:',
    ])
    test_results.bad_test.extend(
        '  ' + repr(s) for s in presentation_steps if s in steps_ran)


def _check_exception(test_results, expected_exception, uncaught_exception_info):
  """Check to see if the test run failed with an exception from RunSteps.

  Args:

    * test_results (Outcome.Results) - The Outcome object to update in
      the event the test exception expectation was bad.
    * expected_exception (str|None) - The name of the exception that the test
      case expected.
    * uncaught_exception_info (Tuple[type, Exception, traceback]|None) - The
      exception info for any uncaught exception triggered by user recipe code.

  Returns CrashFailure|None.
  """
  # Check to see if the user expected the recipe to crash in this test case or
  # not.
  if uncaught_exception_info:
    exc_type, exc, tback = uncaught_exception_info
    exc_name = exc_type.__name__
  else:
    exc_name = exc = None
  if expected_exception:
    if not exc:
      test_results.crash_mismatch.append(
        'Missing expected exception in RunSteps. `api.expect_exception` is'
        ' specified, but the exception did not occur.'
      )

    elif exc_name != expected_exception:
      test_results.crash_mismatch.append(
        'Expected exception mismatch in RunSteps. The test expected %r but '
        'the exception line was %r.' % (expected_exception, exc_name)
      )

  elif exc:
    msg_lines = [
      'Unexpected exception in RunSteps. Use `api.expect_exception` if'
      ' the crash is intentional.',
    ]
    msg_lines += [
      l.rstrip('\n')
      for l in traceback.format_list(extract_tb(tback))
    ]
    msg_lines += [
      l.rstrip('\n')
      for l in traceback.format_exception_only(exc_type, exc)
    ]
    test_results.crash_mismatch.extend(msg_lines)


def _diff_test(test_results, expect_file, new_expect, is_train):
  """Compares the actual and expected results.

  Args:

    * test_results (Outcome.Results) - The object to update in case the diff
      doesn't match up.
    * expect_file (str) - Absolute path to where this test's expectation JSON
      file is.
    * new_expect (Jsonish test expectation) - What the simulation actually
      produced.

  Side-effects:
    * If we're writing the expectation, may update expectation on disk
    * Otherwise, updates test_results if there's a diff with what's on disk.
  """
  cur_expect_text = None
  try:
    with open(expect_file) as fil:
      cur_expect_text = fil.read()
  except IOError:
    pass  # missing, it's fine
  except Exception as ex:  # pylint: disable=broad-except
    if not is_train:
      test_results.internal_error.append(
          'Unexpected exception reading test expectation %r: %r' % (
            expect_file, ex))
      return

  # Occurs if the expectation is not on disk and the test case dropped the
  # expectation data.
  #
  # Otherwise `new_expect_text` will be `null`, which doesn't match None.
  if new_expect is None and cur_expect_text is None:
    return

  new_expect_text = json.dumps(
      _encode_decode(new_expect), sort_keys=True, indent=2,
      separators=(',', ': '),
  )

  if new_expect_text == cur_expect_text:
    return

  # TODO(crbug.com/1211651): py3 expected json file may be different with py2.
  # So they should be generated in a different path. Bypass it for now in
  # `train` command and it will be added in the next CL.
  if is_train and _PY2:
    if new_expect is None:
      try:
        os.remove(expect_file)
        test_results.removed = True
      except OSError:
        pass
      return

    try:
      with open(expect_file, 'wb') as fil:
        fil.write(new_expect_text)
      test_results.written = True
    except Exception as ex:  # pylint: disable=broad-except
      test_results.internal_error.append(
          'Unexpected exception writing test expectation %r: %r' % (
            expect_file, ex))
    return

  if new_expect is None:
    test_results.diff.lines.extend([
      'Test expectation exists on disk at %r.' % (expect_file,),
      'However, the test case dropped all expectation information (i.e. with a'
      ' `post_process` function). Please re-run `recipes.py test train` or '
      'delete this expectation file.',
    ])
    return

  test_results.diff.lines.extend(
      difflib.unified_diff(
          str(cur_expect_text).splitlines(),
          str(new_expect_text).splitlines(),
          fromfile='current expectation file',
          tofile='actual test result',
          n=4, lineterm=''))


def _run_test(path_cleaner, test_results, recipe_deps, test_desc, test_data,
              is_train):
  """This is the main 'function' run by the worker. It executes the test in the
  recipe, compares/diffs/writes the expectation file and updates `test_results`
  as a side effect.

  Args:

    * test_results (Outcome.Results)
    * recipe_deps (RecipeDeps)
    * test_desc (Description)
    * test_data (TestData)
  """
  # Reset global state.
  config_types.ResetTostringFns()
  engine_types.PerGreentletStateRegistry.clear()
  GLOBAL_SHUTDOWN.clear()

  test_case_result = execute_test_case(
        recipe_deps, test_desc.recipe_name, test_data)

  for name, causes in iteritems(test_case_result.warnings):
    test_results.warnings[name].causes.extend(causes)

  raw_expectations = _merge_presentation_updates(test_case_result.ran_steps,
                                                 test_case_result.annotations)
  _check_bad_test(test_results, test_data,
                  list(test_case_result.ran_steps),
                  list(raw_expectations))
  _check_exception(test_results, test_data.expected_exception,
                   test_case_result.uncaught_exception)

  # Convert the result to a json object by dumping to json, and then parsing.
  # TODO(iannucci): Use real objects so this only needs to be serialized once.
  raw_expectations['$result'] = json.loads(jsonpb.MessageToJson(
      legacy.to_legacy_result(test_case_result.raw_result),
      including_default_value_fields=True,
  ))

  raw_expectations['$result']['name'] = '$result'

  raw_expectations = magic_check_fn.post_process(
      test_results, raw_expectations, test_data)

  transform_exepctations(path_cleaner, raw_expectations)

  _diff_test(test_results, test_data.expect_file, raw_expectations, is_train)
  test_results.expect_py_incompatibility = test_desc.expect_py_incompatibility


def _cover_all_imports(main_repo):
  # If our process is supposed to collect coverage for all recipe module
  # imports, do that after we receive the first Description. This way we can
  # reply to the main process with an Outcome. Otherwise the main process
  # could be blocked on writing a Description while we're trying to write an
  # Outcome.
  if not main_repo.modules:
    # Prevents a coverage warning when there are no modules to collect coverage
    # from.
    return coverage.CoverageData()

  cov = coverage.Coverage(
      config_file=False,
      data_file=None,
      include=[os.path.join(main_repo.modules_dir, '*', '*.py')])
  cov.start()
  for module in itervalues(main_repo.modules):
    # Allow exceptions to raise here; they'll be reported as a 'global'
    # failure.
    module.do_import()
  cov.stop()
  return cov.get_data()

# administrative stuff (main, pipe handling, etc.)

def main(recipe_deps, cov_file, filtered_stacks, is_train,
         cover_module_imports):
  if filtered_stacks:
    enable_filtered_stacks()
  gevent.get_hub().exception_stream = None

  main_repo = recipe_deps.main_repo

  cov_data = coverage.CoverageData(basename=cov_file)
  if cover_module_imports:
    cov_data.update(_cover_all_imports(main_repo))

  test_data_cache = {}

  path_cleaner = _make_path_cleaner(recipe_deps)

  fatal = False

  while True:
    test_desc = _read_test_desc()
    if not test_desc:
      break  # EOF or error

    result = Outcome()
    try:
      full_name = '%s.%s' % (test_desc.recipe_name, test_desc.test_name)
      test_result = result.test_results[full_name]

      recipe = main_repo.recipes[test_desc.recipe_name]

      if cov_file:
        # We have to start coverage now because we want to cover the importation
        # of the covered recipe and/or covered recipe modules.
        cov = coverage.Coverage(config_file=False, concurrency='gevent',
                                data_file=None,
                                include=recipe.coverage_patterns)
        cov.start()  # to cover execfile of recipe/module.__init__

      test_data = _get_test_data(test_data_cache, recipe, test_desc.test_name)
      try:
        _run_test(path_cleaner, test_result, recipe_deps, test_desc, test_data,
                  is_train)
      except Exception as ex:  # pylint: disable=broad-except
        test_result.internal_error.append('Uncaught exception: %r' % (ex,))
        test_result.internal_error.extend(traceback.format_exc().splitlines())
      if cov_file:
        cov.stop()
        cov_data.update(cov.get_data())

    except Exception as ex:  # pylint: disable=broad-except
      result.internal_error.append('Uncaught exception: %r' % (ex,))
      result.internal_error.extend(traceback.format_exc().splitlines())
      fatal = True

    if (not write_message(sys.stdout if _PY2 else sys.stdout.buffer, result)
        or fatal):
      break  # EOF

  if cov_file:
      # write data to the cov_file file
      cov_data.write()

def _read_test_desc():
  try:
    return read_message(sys.stdin if _PY2 else sys.stdin.buffer, Description)
  except Exception as ex:  # pylint: disable=broad-except
    write_message(
        sys.stdout if _PY2 else sys.stdout.buffer, Outcome(internal_error=[
          'while reading: %r' % (ex,)
        ]+traceback.format_exc().splitlines()))
    return None

def _get_test_data(cache, recipe, test_name):
  key = (recipe.name, test_name)
  if key not in cache:
    for test_data in recipe.gen_tests():
      cache[(recipe.name, test_data.name)] = test_data
  return cache[key]


# TODO(iannucci): fix test system so that non-JSONish types cannot leak into
# raw_expectations.
def _encode_decode(obj):
  """For py2: ensure consistent encoding for common python data structures.
  For py3: ensure any bytes are decoded to str"""
  if isinstance(obj, basestring):
    if isinstance(obj, bytes):
      obj = obj.decode('utf-8', 'replace')
    return obj.encode('utf-8', 'replace') if _PY2 else obj
  elif isinstance(obj, collections.Mapping):
    return {_encode_decode(k): _encode_decode(v) for k, v in iteritems(obj)}
  elif isinstance(obj, collections.Iterable):
    return [_encode_decode(i) for i in obj]
  else:
    return obj


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
  for repo in itervalues(recipe_deps.repos):
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
  paths = sorted(list(roots), key=lambda v: -len(v))

  # Look for paths in double quotes (as we might see in a stack trace)
  replacer = re.compile(
      r'"(%s)([^"]*)", line (\d+)' % ('|'.join(map(re.escape, paths)),))

  return lambda lines: [replacer.sub(_root_subber, line) for line in lines]


class RunnerThread(gevent.Greenlet):
  def __init__(self, recipe_deps, description_queue, outcome_queue, is_train,
               filtered_stacks, cov_file, cover_module_imports, use_py3):
    super(RunnerThread, self).__init__()

    self.cov_file = cov_file

    py_exec = 'vpython3' if use_py3 else 'vpython'

    cmd = [
      py_exec, '-u', sys.argv[0],
      '--package', os.path.join(
          recipe_deps.main_repo.path, RECIPES_CFG_LOCATION_REL),
      '--proto-override', os.path.dirname(PB.__path__[0]),
      '--log-level', 'ERROR',
    ]
    # Carry through all repos explicitly via overrides
    for repo_name, repo in iteritems(recipe_deps.repos):
      if repo_name == recipe_deps.main_repo.name:
        continue
      cmd.extend(['-O', '%s=%s' % (repo_name, repo.path)])

    cmd.extend(['test', '_runner'])
    if is_train:
      cmd.append('--train')
    if cov_file:
      cmd.extend(['--cov-file', cov_file])
      if cover_module_imports:
        cmd.append('--cover-module-imports')
    if not filtered_stacks:
      cmd.append('--full-stacks')

    self._runner_proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    self._description_queue = description_queue
    self._outcome_queue = outcome_queue

  @classmethod
  def make_pool(cls, recipe_deps, description_queue, outcome_queue, is_train,
                filtered_stacks, collect_coverage, jobs, use_py3):
    """Returns a pool (list) of started RunnerThread instances.

    Each RunnerThread owns a `recipes.py test _runner` subprocess and
    coordinates communication to and from that subprocess.

    This makes `jobs` runners.

    Args:

      * recipe_deps (RecipeDeps)
      * description_queue (gevent.queue.Queue) - The queue to pull Description
        messages from to feed to the runner subprocess.
      * outcome_queue (gevent.queue.Queue) - The queue to push Outcome messages
        sourced from the runner subprocess.
      * is_train (bool) - Whether or not the runner subprocess should train
        (write) expectation files to disk. If False will not write/delete
        anything on the filesystem.
      * filtered_stacks (bool) - If the runner subprocess should enable filtered
        stack traces mode.
      * collect_coverage (bool) - Whether or not to collect coverage. May be
        false if the user specified a test filter.
      * jobs (int) - The number of workers to use for running tests.

    Returns List[RunnerThread].
    """
    if collect_coverage:
      cov_dir = tempfile.mkdtemp('.recipe_test_coverage')
      cov_file = lambda tid: os.path.join(cov_dir, 'thread-%d.coverage' % tid)
    else:
      cov_dir = None
      cov_file = lambda tid: None

    # We assign import coverage to (only) the first runner subprocess; there's
    # no need to duplicate this work to all runners.
    pool = [
        cls(recipe_deps,
            description_queue,
            outcome_queue,
            is_train,
            filtered_stacks,
            cov_file(i),
            cover_module_imports=(i == 0),
            use_py3 = use_py3) for i in range(jobs)
    ]
    for thread in pool:
      thread.start()
    return cov_dir, pool

  # pylint: disable=method-hidden
  def _run(self):
    try:
      while True:
        test_desc = self._description_queue.get()
        if not test_desc:
          self._runner_proc.stdout.close()
          try:
            self._runner_proc.stdin.write('\0')
            self._runner_proc.stdin.close()
          except OSError as e:
            # The subprocess has already aborted in starting stage.
            if e.errno == errno.EPIPE:
              pass
          self._runner_proc.wait()
          return

        if not write_message(self._runner_proc.stdin, test_desc):
          self._outcome_queue.put(Outcome(internal_error=[
            'Unable to send test description for (%s.%s) from %r' % (
              test_desc.recipe_name, test_desc.test_name, self.name
            )
          ]))
          return

        result = read_message(self._runner_proc.stdout, Outcome)
        if result is None:
          return

        self._outcome_queue.put(result)
    except KeyboardInterrupt:
      pass
    except gevent.GreenletExit:
      pass
    except Exception as ex:  # pylint: disable=broad-except
      self._outcome_queue.put(Outcome(internal_error=[
        'Uncaught exception in %r: %s' % (self.name, ex)
      ]+traceback.format_exc().splitlines()))
    finally:
      try:
        self._runner_proc.kill()
      except OSError:
        pass
      self._runner_proc.wait()
      # We rely on the thread to dump coverage information to disk; if we don't
      # wait for the process to die, then our main thread will race with the
      # runner thread for the coverage information. On windows this almost
      # always causes an IOError, on *nix this will likely result in flakily
      # truncated coverage files.
      #
      # Sending ourselves down the pipe lets the main process know that we've
      # quit so it can remove us from the live threads.
      self._outcome_queue.put(self)
