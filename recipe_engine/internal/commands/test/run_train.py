# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime
import errno
import fnmatch
import json
import os
import re
import shutil

from cStringIO import StringIO

import coverage
import gevent
import gevent.queue

from backports.shutil_get_terminal_size import get_terminal_size

from google.protobuf import json_format

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

# pylint: disable=import-error
from PB.recipe_engine.internal.test.runner import Description, Outcome

from ..doc.cmd import regenerate_docs

from . import report
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


def _push_tests(test_filters, is_train, main_repo, description_queue):
  recipe_filter, test_filter = _extract_filter_matchers(test_filters)

  unused_expectation_files = set()
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

    used_expectations = set()

    # Maps expect_file -> original test_name
    test_filenames = {}
    try:
      for test_case in recipe.gen_tests():  # User code, could raise
        expect_file = test_case.expect_file
        used_expectations.add(expect_file)
        if expect_file in test_filenames:
          og_name = test_filenames[expect_file]
          if og_name == test_case.name:
            raise ValueError(
                'Emitted test with duplicate name %r' % (test_case.name,))
          else:
            raise ValueError(
                'Emitted test %r which maps to the same JSON file as %r: %r' %
                (test_case.name, og_name, expect_file))
        test_filenames[expect_file] = test_case.name
        if not test_filter('%s.%s' % (recipe.name, test_case.name)):
          continue

        description_queue.put(Description(
            recipe_name=recipe.name,
            test_name=test_case.name,
        ))
        gevent.sleep()  # let any blocking threads pick this up
    except KeyboardInterrupt:
      raise
    except:
      print "USER CODE ERROR:"
      print "Crashed while running GenTests from recipe %r" % (recipe.name,)
      raise

    unused_expectation_files |= recipe.expectation_paths - used_expectations

  if not is_train:
    return unused_expectation_files

  for path in unused_expectation_files:
    os.remove(path)
  return set()


def _run(test_result, recipe_deps, test_filters, is_train):
  start_time = datetime.datetime.now()
  main_repo = recipe_deps.main_repo

  description_queue = gevent.queue.UnboundQueue()
  outcome_queue = gevent.queue.UnboundQueue()

  test_result.uncovered_modules.extend(sorted(
      set(main_repo.modules.keys())
      - set(
          module.name
          for module in main_repo.modules.itervalues()
          if module.uses_sloppy_coverage or module.recipes
      )
  ))

  try:
    # in case of crash; don't want this undefined in finally clause.
    live_threads = []
    cov_dir, all_threads = RunnerThread.make_pool(
        recipe_deps, description_queue, outcome_queue, is_train,
        collect_coverage=not test_filters)
    live_threads = list(all_threads)

    test_result.unused_expectation_files.extend(sorted(
        _push_tests(test_filters, is_train, main_repo, description_queue)))

    # Put a None poison pill for each thread.
    for thread in all_threads:
      description_queue.put(None)

    err_buf = StringIO()
    emoji_count = 0
    # all emoji are 2 columns wide; default to 80 cols if we can't figure out
    # the width (or are on a bot), and then prevent emoji_max from ever falling
    # below 1 (to avoid division by 0)
    emoji_max = max(1, (get_terminal_size().columns or 80) / 2)
    while live_threads:
      rslt = outcome_queue.get()
      if rslt is None:
        live_threads = [thread for thread in live_threads if not thread.dead]
      else:
        test_result.MergeFrom(rslt)

        report.test_cases_to_stdout(rslt, err_buf)
        emoji_count += 1
        if not report.VERBOSE:
          if (emoji_count % emoji_max) == 0:
            emoji_count = 0
            print

    # At this point we know all subprocesses and their threads have finished
    # (because outcome_queue has been closed by each worker, which is how we
    # escaped the loop above).
    #
    # If we don't have any filters, collect coverage data.
    cov = None
    if not test_filters:
      cov = coverage.Coverage(config_file=False)
      cov.get_data()  # initializes data object
      for thread in all_threads:
        thread_data = coverage.CoverageData()
        thread_data.read_file(thread.cov_file)
        cov.data.update(thread_data)

    report.final_summary_to_stdout(
        err_buf, is_train, cov, test_result, start_time)

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
    _run(ret, args.recipe_deps, args.test_filters, is_train)
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
