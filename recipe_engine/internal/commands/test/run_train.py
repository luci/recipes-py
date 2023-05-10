# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function
from future.utils import iteritems, itervalues

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
from .runner import RunnerThread, DescriptionWithCallback


TestResults = collections.namedtuple('TestResults', 'py3')
Queue = collections.namedtuple('Queue', 'py3')
Threads = collections.namedtuple('Threads', 'py3')


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
  """
  unused_expectation_files = set()
  used_expectation_files = set()
  recipe_filter, test_filter = _extract_filter_matchers(test_filters)
  test_filenames = collections.defaultdict(dict)

  def push_test(recipe, test_case):
    recipe_filenames = test_filenames[recipe]
    expect_file = test_case.expect_file
    used_expectation_files.add(expect_file)
    if expect_file in recipe_filenames:
      og_name = recipe_filenames[expect_file]
      if og_name == test_case.name:
        raise ValueError(
            'Emitted test with duplicate name %r' % (test_case.name,))

      raise ValueError(
          'Emitted test %r which maps to the same JSON file as %r: %r' %
          (test_case.name, og_name, expect_file))

    recipe_filenames[expect_file] = test_case.name
    if not test_filter('%s.%s' % (recipe.name, test_case.name)):
      return

    description_queues.py3.put(
        Description(
            recipe_name=recipe.name,
            test_name=test_case.name))

    gevent.sleep()  # let any blocking threads pick this up

  # If filters are enabled, we'll only clean up expectation files for recipes
  # that are included by the filter.
  if not test_filters:
    unused_expectation_files.update(main_repo.expectation_paths)

  # Handle recent fails first
  deferred_tests = []
  for recipe in itervalues(main_repo.recipes):
    if not recipe_filter(recipe.name):
      continue

    if test_filters:
      unused_expectation_files.update(recipe.expectation_paths)

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
    return sorted(unused_expectation_files)

  for path in unused_expectation_files:
    os.remove(path)
  return set()


def _run(test_results, recipe_deps, use_emoji, test_filters, is_train,
         filtered_stacks, stop, jobs, show_warnings):
  """Run tests in py3 subprocess pools.
  """
  main_repo = recipe_deps.main_repo

  description_queues = Queue(py3=gevent.queue.UnboundQueue())

  # outcome_queue is written to by RunnerThreads; it will either contain Outcome
  # messages, or it will contain one of our RunnerThread instances (to indicate
  # to our main thread here that the RunnerThread is done).
  outcome_queues = Queue(py3=gevent.queue.UnboundQueue())

  for test_result in test_results:
    test_result.uncovered_modules.extend(sorted(
        set(
            module.name
            for module in itervalues(main_repo.modules)
            if not (
              module.uses_sloppy_coverage or module.recipes or module.warnings)
        )
    ))

  fail_tracker = FailTracker(recipe_deps.previous_test_failures_path)
  reporter = report.Reporter(recipe_deps, use_emoji, is_train, fail_tracker,
                             show_warnings, True)

  py3_cov_dir = None
  total_cov = coverage.Coverage(config_file=False, data_file='.total_coverage',
                                data_suffix=True)
  total_cov.save() # Force to ensure the coverage data file is created.
  try:
    # in case of crash; don't want this undefined in finally clause.
    live_threads = Threads(py3=[])

    py3_cov_dir, py3_all_threads = RunnerThread.make_pool(
        recipe_deps,
        description_queues.py3,
        outcome_queues.py3,
        is_train,
        filtered_stacks,
        collect_coverage=not test_filters,
        jobs=jobs)
    live_threads.py3[:] = py3_all_threads
    all_threads = Threads(py3=py3_all_threads)

    unused_expectation_files = _push_tests(
        test_filters, is_train, main_repo, description_queues,
        fail_tracker.recent_fails)
    for test_result in test_results:
      test_result.unused_expectation_files.extend(unused_expectation_files)

    def execute_queue():
      has_fail = False
      implicit_py3_err = 0

      threads = live_threads.py3
      while threads and not (has_fail and stop):
        rslt = outcome_queues.py3.get()
        if isinstance(rslt, RunnerThread):
          # should be done at this point, but make sure for cleanliness sake.
          gevent.wait([rslt])
          threads.remove(rslt)
          continue

        test_results.py3.MergeFrom(rslt)
        has_fail, count = reporter.short_report(rslt, can_abort=True)
        implicit_py3_err += count
        if has_fail and stop:
          break

      # At this point we know all subprocesses and their threads have finished
      # (because outcome_queue has been closed by each worker, which is how we
      # escaped the while loop above).
      #
      # If we don't have any filters, collect coverage data.
      if (test_filters or (stop and has_fail)) is False:
        data_paths = [t.cov_file for t in all_threads.py3
                      if os.path.isfile(t.cov_file)]
        if data_paths:
          total_cov.combine(data_paths)

      return has_fail

    # Put None poison pill for each thread.
    for thread in all_threads.py3:
      description_queues.py3.put(None)

    has_fail = execute_queue()
    print()

    # Don't display coverage if the --stop flag was specified and there's a
    # failure
    if has_fail and stop:
      reporter.final_report(None, test_results)
    else:
      reporter.final_report(total_cov, test_results)

  finally:
    for thread in live_threads.py3:
      thread.kill()
      thread.join()
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
  ret = TestResults(py3=Outcome())

  if args.filtered_stacks:
    enable_filtered_stacks()
    print('Filtering engine implementation out of crash stacks. '
          'Pass `--full-stacks` to see entire stack.')

  def _dump():
    if args.json:
      output = []
      result = json_format.MessageToDict(ret.py3, preserving_proto_field_name=True)
      output.append(result)
      json.dump(output, args.json)

    if args.dump_timing_info:
      for testname, result in iteritems(ret.py3.test_results):
        as_string = json_format.MessageToJson(result.duration)
        args.dump_timing_info.write('%s\t%s\n' % (
            testname,
            # Durations are encoded like "0.23s". We just want the raw number
            # to be put into the file, so skip the first and last quote, and
            # the 's'.
            as_string[1:-2]))

  repo = args.recipe_deps.main_repo
  try:
    _run(ret, args.recipe_deps, args.use_emoji, args.test_filters, is_train,
         args.filtered_stacks, args.stop, args.jobs, args.show_warnings)
    _dump()
  except KeyboardInterrupt:
    args.docs = False  # skip docs
  except SystemExit:
    _dump()
    raise

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
