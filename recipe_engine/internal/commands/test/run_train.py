# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

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

# pylint: disable=import-error
from PB.recipe_engine.internal.test.runner import Description, Outcome

from ..doc.cmd import regenerate_doc, doc_diff

from . import report, test_name
from .fail_tracker import FailTracker
from .runner import RunnerThread


# TODO(crbug.com/1147793): Remove the second return value after migration.
def _push_tests(test_filter: test_name.Filter, is_train, main_repo, description_queue,
                recent_fails):
  """
  Returns:
    * set - unused_expectation_files
  """
  unused_expectation_files = set()
  used_expectation_files = set()
  test_filenames = collections.defaultdict(dict)

  def push_test(recipe, test_case):
    recipe_filenames = test_filenames[recipe]
    expect_file = test_case.expect_file
    used_expectation_files.add(expect_file)
    if expect_file in recipe_filenames:
      og_name = recipe_filenames[expect_file]
      if og_name == test_case.name:
        raise ValueError(
            f'Emitted test with duplicate name {test_case.name!r}')

      raise ValueError(
          'Emitted test %r which maps to the same JSON file as %r: %r' %
          (test_case.name, og_name, expect_file))

    recipe_filenames[expect_file] = test_case.name
    if not test_filter.full_name(f'{recipe.name}.{test_case.name}'):
      return

    description_queue.put(
        Description(
            recipe_name=recipe.name,
            test_name=test_case.name))

    gevent.sleep()  # let any blocking threads pick this up

  # If filters are enabled, we'll only clean up expectation files for recipes
  # that are included by the filter.
  if not test_filter:
    unused_expectation_files.update(main_repo.expectation_paths)

  # Handle recent fails first
  deferred_tests = []
  for recipe in main_repo.recipes.values():
    if not test_filter.recipe_name(recipe.name):
      continue

    if test_filter:
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
      print('USER CODE ERROR:')
      print(f'Crashed while running GenTests from recipe {recipe.name}')
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


def _run(test_results, recipe_deps, use_emoji, test_filter, is_train,
         stop, jobs, show_warnings, show_durations):
  """Run tests in py3 subprocess pools.
  """
  main_repo = recipe_deps.main_repo

  description_queue = gevent.queue.UnboundQueue()

  # outcome_queue is written to by RunnerThreads; it will either contain Outcome
  # messages, or it will contain one of our RunnerThread instances (to indicate
  # to our main thread here that the RunnerThread is done).
  outcome_queue = gevent.queue.UnboundQueue()

  test_results.uncovered_modules.extend(sorted(
      set(
          module.name
          for module in main_repo.modules.values()
          if not (
            module.uses_sloppy_coverage or module.recipes or module.warnings)
      )
  ))

  fail_tracker = FailTracker(recipe_deps.previous_test_failures_path)
  reporter = report.Reporter(recipe_deps, use_emoji, is_train, fail_tracker,
                             show_warnings, show_durations)

  cov_dir = None
  total_cov = coverage.Coverage(config_file=False, data_file='.total_coverage',
                                data_suffix=True)
  total_cov.save() # Force to ensure the coverage data file is created.
  try:
    # in case of crash; don't want this undefined in finally clause.
    live_threads = []

    cov_dir, all_threads = RunnerThread.make_pool(
        recipe_deps,
        description_queue,
        outcome_queue,
        is_train,
        collect_coverage=not test_filter,
        jobs=jobs)
    live_threads[:] = all_threads

    unused_expectation_files = _push_tests(
        test_filter, is_train, main_repo, description_queue,
        fail_tracker.recent_fails)
    test_results.unused_expectation_files.extend(unused_expectation_files)

    def execute_queue():
      has_fail = False

      while live_threads and not (has_fail and stop):
        rslt = outcome_queue.get()
        if isinstance(rslt, RunnerThread):
          # should be done at this point, but make sure for cleanliness sake.
          gevent.wait([rslt])
          live_threads.remove(rslt)
          continue

        test_results.MergeFrom(rslt)
        has_fail = reporter.short_report(rslt, can_abort=True)
        if has_fail and stop:
          break

      # At this point we know all subprocesses and their threads have finished
      # (because outcome_queue has been closed by each worker, which is how we
      # escaped the while loop above).
      #
      # If we don't have any filters, collect coverage data.
      if (test_filter or (stop and has_fail)) is False:
        data_paths = [t.cov_file for t in all_threads
                      if os.path.isfile(t.cov_file)]
        if data_paths:
          total_cov.combine(data_paths)

      return has_fail

    # Put None poison pill for each thread.
    for thread in all_threads:
      description_queue.put(None)

    has_fail = execute_queue()
    print()

    # Don't display coverage if the --stop flag was specified and there's a
    # failure
    if has_fail and stop:
      reporter.final_report(None, test_results)
    else:
      reporter.final_report(total_cov, test_results)

  finally:
    for thread in live_threads:
      thread.kill()
      thread.join()
    if cov_dir:
      shutil.rmtree(cov_dir, ignore_errors=True)
    total_cov.erase()

def main(args):
  """Runs simulation tests on a given repo of recipes.

  Args:
    args: the parsed args (see add_subparser).
  Returns:
    Exit code
  """
  is_train = args.subcommand == 'train'
  ret = Outcome()

  def _dump():
    if args.json:
      output = []
      result = json_format.MessageToDict(ret, preserving_proto_field_name=True)
      output.append(result)
      json.dump(output, args.json)

    if args.dump_timing_info:
      for testname, result in ret.test_results.items():
        as_string = json_format.MessageToJson(result.duration)
        args.dump_timing_info.write('%s\t%s\n' % (
            testname,
            # Durations are encoded like "0.23s". We just want the raw number
            # to be put into the file, so skip the first and last quote, and
            # the 's'.
            as_string[1:-2]))

  repo = args.recipe_deps.main_repo
  try:
    _run(ret, args.recipe_deps, args.use_emoji, args.test_filter, is_train,
         args.stop, args.jobs, args.show_warnings, args.show_durations)
    _dump()
  except KeyboardInterrupt:
    args.docs = False  # skip docs
  except SystemExit:
    _dump()
    raise

  docs_enabled = (not repo.recipes_cfg_pb2.no_docs) and args.docs
  is_run = args.subcommand == 'run'
  if docs_enabled:
    if is_run and doc_diff(repo):
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
