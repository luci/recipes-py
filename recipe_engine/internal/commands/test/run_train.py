# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import errno
import fnmatch
import json
import os
import re
import shutil

import coverage
import gevent
import gevent.queue

from google.protobuf import json_format

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

# pylint: disable=import-error
from PB.recipe_engine.internal.test.runner import Description, Outcome

from ..doc.cmd import regenerate_docs

from . import report
from .fail_tracker import FailTracker
from .runner import RunnerThread


def _extract_filter_matchers(test_filters):
  if not test_filters:
    return (
      (lambda _recipe_name: True),
      (lambda _full_test_case_name: True),
    )

  return (
    re.compile('|'.join([
      fnmatch.translate(pattern.split('.', 1)[0])
      for pattern in test_filters
    ])).match,
    re.compile('|'.join([
      fnmatch.translate(pattern)
      for pattern in test_filters
    ])).match
  )


def _push_tests(test_filters, is_train, main_repo, description_queue,
                recent_fails):
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
      else:
        raise ValueError(
            'Emitted test %r which maps to the same JSON file as %r: %r' %
            (test_case.name, og_name, expect_file))
    recipe_filenames[expect_file] = test_case.name
    if not test_filter('%s.%s' % (recipe.name, test_case.name)):
      return

    description_queue.put(
        Description(
            recipe_name=recipe.name,
            test_name=test_case.name,
        ))
    gevent.sleep()  # let any blocking threads pick this up

  # Handle recent fails first
  deferred_tests = []
  for recipe in main_repo.recipes.itervalues():
    if not recipe_filter(recipe.name):
      continue

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
      print "USER CODE ERROR:"
      print "Crashed while running GenTests from recipe %r" % (recipe.name,)
      raise

    unused_expectation_files |= recipe.expectation_paths

  # Test any non-recently-failed cases
  for deferred_test in deferred_tests:
    push_test(*deferred_test)

  unused_expectation_files -= used_expectation_files
  if not is_train:
    return unused_expectation_files

  for path in unused_expectation_files:
    os.remove(path)
  return set()


def _run(test_result, recipe_deps, use_emoji, test_filters, is_train, stop):
  main_repo = recipe_deps.main_repo

  description_queue = gevent.queue.UnboundQueue()

  # outcome_queue is written to by RunnerThreads; it will either contain Outcome
  # messages, or it will contain one of our RunnerThread instances (to indicate
  # to our main thread here that the RunnerThread is done).
  outcome_queue = gevent.queue.UnboundQueue()

  test_result.uncovered_modules.extend(sorted(
      set(main_repo.modules.keys())
      - set(
          module.name
          for module in main_repo.modules.itervalues()
          if module.uses_sloppy_coverage or module.recipes
      )
  ))

  fail_file_path = os.path.join(recipe_deps.recipe_deps_path,
                                '.previous_test_failures')
  fail_tracker = FailTracker(fail_file_path)
  reporter = report.Reporter(use_emoji, is_train, fail_tracker)

  cov_dir = None
  try:
    # in case of crash; don't want this undefined in finally clause.
    live_threads = []
    cov_dir, all_threads = RunnerThread.make_pool(
        recipe_deps, description_queue, outcome_queue, is_train,
        collect_coverage=not test_filters)
    live_threads = list(all_threads)

    test_result.unused_expectation_files.extend(
        sorted(
            _push_tests(test_filters, is_train, main_repo, description_queue,
                        fail_tracker.recent_fails)))

    # Put a None poison pill for each thread.
    for thread in all_threads:
      description_queue.put(None)

    has_fail = False
    while live_threads:
      rslt = outcome_queue.get()
      if isinstance(rslt, RunnerThread):
        # should be done at this point, but make sure for cleanliness sake.
        gevent.wait([rslt])
        live_threads.remove(rslt)
        continue

      test_result.MergeFrom(rslt)
      has_fail = reporter.short_report(rslt)
      if has_fail and stop:
        break

    # At this point we know all subprocesses and their threads have finished
    # (because outcome_queue has been closed by each worker, which is how we
    # escaped the loop above).
    #
    # If we don't have any filters, collect coverage data.

    cov = None
    if (test_filters or (stop and has_fail)) is False:
      cov = coverage.Coverage(config_file=False)
      cov.get_data()  # initializes data object
      for thread in all_threads:
        thread_data = coverage.CoverageData()
        thread_data.read_file(thread.cov_file)
        cov.data.update(thread_data)

    reporter.final_report(cov, test_result)

  finally:
    for thread in live_threads:
      thread.kill()
      thread.join()
    if cov_dir:
      shutil.rmtree(cov_dir, ignore_errors=True)


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
      json.dump(
          json_format.MessageToDict(ret, preserving_proto_field_name=True),
          args.json)

  try:
    _run(ret, args.recipe_deps, args.use_emoji, args.test_filters, is_train,
         args.stop)
    _dump()
  except KeyboardInterrupt:
    args.docs = False  # skip docs
  except SystemExit:
    _dump()
    raise

  if is_train and args.docs:
    print 'Generating README.recipes.md'
    regenerate_docs(args.recipe_deps.main_repo)
  return 0
