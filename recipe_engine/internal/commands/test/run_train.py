# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import collections
import errno
import fnmatch
import io
import json
import os
import re
import shutil
import sys

import coverage
import gevent
import gevent.queue

from google.protobuf import json_format

from recipe_engine import __path__ as RECIPE_ENGINE_PATH
from recipe_engine.util import enable_filtered_stacks

# pylint: disable=import-error
from PB.recipe_engine.internal.test.runner import Description, Outcome

from ..doc.cmd import regenerate_doc, is_doc_changed

from . import report, test_name
from .fail_tracker import FailTracker
from .runner import RunnerThread


TestResults = collections.namedtuple('TestResults', 'py2 py3')
Queue = collections.namedtuple('Queue', 'py2 py3')
Threads = collections.namedtuple('Threads', 'py2 py3')

_PY2 = sys.version_info.major == 2

def _extract_filter_matchers(test_filters):
  if not test_filters:
    return (
      (lambda _recipe_name: True),
      (lambda _full_test_case_name: True),
    )

  return (
    re.compile('|'.join([
      fnmatch.translate(test_name.split(pattern)[0])
      for pattern in test_filters
    ])).match,
    re.compile('|'.join([
      fnmatch.translate(pattern)
      for pattern in test_filters
    ])).match
  )


# TODO(crbug.com/1147793): Remove the second return value after migration.
def _push_tests(test_filters, is_train, main_repo, description_queues,
                recent_fails):
  """
  Returns:
    * set - unused_expectation_files
    * bool - has_labeled_recipe. This is introduced temporarily for migration.
             Because we want to always run all tests in py3. To decide whether
             or not to abort the program earlier due to a global failure (see
             first few lines of code in reporter.short_report() about this f
             ailure), we need to know if users have started migrating:
                * If not, the global failure shouldn't cause an abort.
                * If migration has started, abort and let them see this error.
  """
  unused_expectation_files = set()
  used_expectation_files = set()
  recipe_filter, test_filter = _extract_filter_matchers(test_filters)
  test_filenames = collections.defaultdict(dict)
  has_labeled_recipe = [False]

  def push_test(recipe, test_case):
    recipe_filenames = test_filenames[recipe]
    expect_file = test_case.expect_file
    used_expectation_files.add(expect_file)
    if expect_file in recipe_filenames:
      og_name = recipe_filenames[expect_file]
      if og_name == test_case.name:
        raise ValueError(
            'Emitted test with duplicate name %r' % (test_case.name,))
      else:
        raise ValueError(
            'Emitted test %r which maps to the same JSON file as %r: %r' %
            (test_case.name, og_name, expect_file))
    recipe_filenames[expect_file] = test_case.name
    if not test_filter('%s.%s' % (recipe.name, test_case.name)):
      return

    if recipe.is_python_version_labeled:
      has_labeled_recipe[0] = True
    # Put into both py2 and py3 pools by default, unless this recipe's python
    # compatibility is explicitly labeled.
    if not recipe.is_python_version_labeled:
      description_queues.py2.put(
          Description(
              recipe_name=recipe.name,
              test_name=test_case.name,
              expect_py_incompatibility=(
                  not recipe.effective_python_compatibility)
          ))
      description_queues.py3.put(
          Description(
              recipe_name=recipe.name,
              test_name=test_case.name,
              expect_py_incompatibility=True  # unlabeled val is regarded as py2
          ))
    elif recipe.python_version_compatibility == 'PY3':
      description_queues.py3.put(
          Description(
              recipe_name=recipe.name,
              test_name=test_case.name,
              expect_py_incompatibility=(
                  not recipe.effective_python_compatibility),
              is_labeled=True,
          ))
    elif recipe.python_version_compatibility == 'PY2+3':
      description_queues.py2.put(
          Description(
              recipe_name=recipe.name,
              test_name=test_case.name,
              expect_py_incompatibility=(
                  True if recipe.effective_python_compatibility in (None, 'PY3')
                  else False),
              is_labeled=True,
          ))
      description_queues.py3.put(
          Description(
              recipe_name=recipe.name,
              test_name=test_case.name,
              expect_py_incompatibility=(
                  True if recipe.effective_python_compatibility in (None, 'PY2')
                  else False),
              is_labeled=True,
          ))
    else:
      description_queues.py2.put(
        Description(
          recipe_name=recipe.name,
          test_name=test_case.name,
          expect_py_incompatibility=not recipe.effective_python_compatibility,
          is_labeled=True,
        ))
    gevent.sleep()  # let any blocking threads pick this up

  # If filters are enabled, we'll only clean up expectation files for recipes
  # that are included by the filter.
  if not test_filters:
    unused_expectation_files.update(main_repo.expectation_paths)

  # Handle recent fails first
  deferred_tests = []
  for recipe in main_repo.recipes.itervalues():
    if not recipe_filter(recipe.name):
      continue

    if test_filters:
      unused_expectation_files.update(recipe.expectation_paths)

    if is_train:
      # Try to make the expectation dir.
      try:
        os.makedirs(recipe.expectation_dir)
      except OSError as ex:
        if ex.errno != errno.EEXIST:
          raise

    # Maps expect_file -> original test_name
    try:
      for test_case in recipe.gen_tests():  # User code, could raise
        full_name = recipe.full_name.split('::')[-1] + '.' + test_case.name
        if len(recent_fails) == 0 or full_name in recent_fails:
          push_test(recipe, test_case)
        else:
          deferred_tests.append((recipe, test_case))
    except KeyboardInterrupt:
      raise
    except:
      print("USER CODE ERROR:")
      print("Crashed while running GenTests from recipe %r" % (recipe.name,))
      raise

  # Test any non-recently-failed cases
  for deferred_test in deferred_tests:
    push_test(*deferred_test)

  unused_expectation_files -= used_expectation_files
  if not is_train:
    return sorted(unused_expectation_files), has_labeled_recipe[0]

  for path in unused_expectation_files:
    os.remove(path)
  return set(), has_labeled_recipe[0]


def _run(test_results, recipe_deps, use_emoji, test_filters, is_train,
         filtered_stacks, stop, jobs, enable_py3_details):
  main_repo = recipe_deps.main_repo

  description_queues = Queue(py2=gevent.queue.UnboundQueue(),
                             py3=gevent.queue.UnboundQueue())

  # outcome_queue is written to by RunnerThreads; it will either contain Outcome
  # messages, or it will contain one of our RunnerThread instances (to indicate
  # to our main thread here that the RunnerThread is done).
  outcome_queues = Queue(py2=gevent.queue.UnboundQueue(),
                         py3=gevent.queue.UnboundQueue())

  for test_result in test_results:
    test_result.uncovered_modules.extend(sorted(
        set(main_repo.modules.keys())
        - set(
            module.name
            for module in main_repo.modules.itervalues()
            if module.uses_sloppy_coverage or module.recipes
        )
    ))

  fail_tracker = FailTracker(recipe_deps.previous_test_failures_path)
  reporter = report.Reporter(use_emoji, is_train, fail_tracker,
                             enable_py3_details)

  py2_cov_dir = None
  py3_cov_dir = None
  total_cov = coverage.Coverage(config_file=False)
  try:
    # in case of crash; don't want this undefined in finally clause.
    live_threads = Threads(py2=[], py3=[])

    py2_cov_dir, py2_all_threads = RunnerThread.make_pool(
        recipe_deps,
        description_queues.py2,
        outcome_queues.py2,
        is_train,
        filtered_stacks,
        collect_coverage=not test_filters,
        jobs=jobs,
        use_py3=False)
    live_threads.py2[:] = py2_all_threads

    py3_cov_dir, py3_all_threads = RunnerThread.make_pool(
        recipe_deps,
        description_queues.py3,
        outcome_queues.py3,
        is_train,
        filtered_stacks,
        collect_coverage=not test_filters,
        jobs=jobs,
        use_py3=True,
        enable_py3_details=enable_py3_details)
    live_threads.py3[:] = py3_all_threads
    all_threads = Threads(py2=py2_all_threads, py3=py3_all_threads)

    unused_expectation_files, has_labeled_recipe = _push_tests(
        test_filters, is_train, main_repo, description_queues,
        fail_tracker.recent_fails)
    for test_result in test_results:
      test_result.unused_expectation_files.extend(unused_expectation_files)

    # Put a None poison pill for each thread.
    for thread in all_threads.py2:
      description_queues.py2.put(None)
    for thread in all_threads.py3:
      description_queues.py3.put(None)

    has_fail = False
    implicit_py3_err = 0
    for py in live_threads._fields:
      print('\nRunning tests in %s' % py)
      threads = getattr(live_threads, py)
      has_unexpected_fail = False
      while threads and not (has_fail and stop):
        rslt = getattr(outcome_queues, py).get()
        if isinstance(rslt, RunnerThread):
          if rslt.exit_code and rslt.exit_code > 0:
            has_unexpected_fail = True
          # should be done at this point, but make sure for cleanliness sake.
          gevent.wait([rslt])
          threads.remove(rslt)
          continue

        getattr(test_results, py).MergeFrom(rslt)
        has_fail, count = reporter.short_report(rslt, py, can_abort=(
            py == 'py2' or has_labeled_recipe))
        implicit_py3_err += count
        if has_fail and stop:
          break

      if py == 'py3' and not enable_py3_details:
        if has_unexpected_fail:
          print('WARNING: unexpected errors occurred when trying to run tests '
                'in python3 mode. Pass --py3-details to see them.')
          continue
        if implicit_py3_err > 0:
          print('WARNING: Ignored %d failures in implicit py3 tests for recipes'
                ' that don\'t declare their own PYTHON_VERSION_COMPATIBILITY. '
                'Pass --py3-details to see them.' % implicit_py3_err)

      # At this point we know all subprocesses and their threads have finished
      # (because outcome_queue has been closed by each worker, which is how we
      # escaped the while loop above).
      #
      # If we don't have any filters, collect coverage data.
      if (test_filters or (stop and has_fail)) is False:
        data_paths = [t.cov_file for t in getattr(all_threads, py)
                      if os.path.isfile(t.cov_file)]
        if data_paths:
          total_cov.combine(data_paths)

    reporter.final_report(total_cov, test_results, recipe_deps)

  finally:
    for thread in live_threads.py2 + live_threads.py3:
      thread.kill()
      thread.join()
    if py2_cov_dir:
      shutil.rmtree(py2_cov_dir, ignore_errors=True)
    if py3_cov_dir:
      shutil.rmtree(py3_cov_dir, ignore_errors=True)
    total_cov.erase()


def main(args):
  """Runs simulation tests on a given repo of recipes.

  Args:
    args: the parsed args (see add_subparser).
  Returns:
    Exit code
  """
  is_train = args.subcommand == 'train'
  ret = TestResults(py2=Outcome(), py3=Outcome())

  if args.filtered_stacks:
    enable_filtered_stacks()
    print('Filtering engine implementation out of crash stacks. '
          'Pass `--full-stacks` to see entire stack.')

  def _dump():
    if args.json:
      output = []
      for name, r in ret._asdict().iteritems():
        result = json_format.MessageToDict(r, preserving_proto_field_name=True)
        result['python_env'] = name
        output.append(result)
      json.dump(output, args.json)

  try:
    _run(ret, args.recipe_deps, args.use_emoji, args.test_filters, is_train,
         args.filtered_stacks, args.stop, args.jobs, args.py3_details)
    _dump()
  except KeyboardInterrupt:
    args.docs = False  # skip docs
  except SystemExit:
    _dump()
    raise

  repo = args.recipe_deps.main_repo
  docs_enabled = (not repo.recipes_cfg_pb2.no_docs) and args.docs
  is_run = args.subcommand == 'run'
  if docs_enabled:
    if is_run and is_doc_changed(repo):
      print('------')
      print('README.recipes.md needs to be updated. Please run:')
      print()
      print('  ./recipes.py doc')
      print()
      return 1

    if is_train:
      print('Generating README.recipes.md')
      with open(repo.readme_path, 'w') as f:
        regenerate_doc(repo, f)

  return 0
