# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import Queue
import glob
import logging
import multiprocessing
import re
import signal
import traceback

from cStringIO import StringIO

from .type_definitions import (
    Test, UnknownError, TestError, NoMatchingTestsError, MultiTest,
    Result, ResultStageAbort)


class ResetableStringIO(object):
  def __init__(self):
    self._stream = StringIO()

  def reset(self):
    self._stream = StringIO()

  def __getattr__(self, key):
    return getattr(self._stream, key)


def gen_loop_process(gen, test_queue, result_queue, opts, kill_switch,
                     cover_ctx):
  """Generate `Test`'s from |gen|, and feed them into |test_queue|.

  Non-Test instances will be translated into `UnknownError` objects.

  On completion, feed |opts.jobs| None objects into |test_queue|.

  @param gen: generator yielding Test() instances.
  @type test_queue: multiprocessing.Queue()
  @type result_queue: multiprocessing.Queue()
  @type opts: argparse.Namespace
  @type kill_switch: multiprocessing.Event()
  @type cover_ctx: cover.CoverageContext().create_subprocess_context()
  """
  # Implicitly append '*'' to globs that don't specify it.
  globs = ['%s%s' % (g, '*' if '*' not in g else '') for g in opts.test_glob]

  matcher = re.compile(
      '^%s$' % '|'.join('(?:%s)' % glob.fnmatch.translate(g)
                        for g in globs if g[0] != '-'))
  if matcher.pattern == '^$':
    matcher = re.compile('^.*$')

  neg_matcher = re.compile(
      '^%s$' % '|'.join('(?:%s)' % glob.fnmatch.translate(g[1:])
                        for g in globs if g[0] == '-'))

  def generate_tests():
    paths_seen = set()
    seen_tests = False
    try:
      for root_test in gen():
        if kill_switch.is_set():
          break

        ok_tests = []

        if isinstance(root_test, MultiTest):
          subtests = root_test.tests
        else:
          subtests = [root_test]

        for subtest in subtests:
          if not isinstance(subtest, Test):
            result_queue.put_nowait(
                UnknownError('Got non-[Multi]Test isinstance from generator: %r'
                             % subtest))
            continue

          test_path = subtest.expect_path()
          if test_path is not None and test_path in paths_seen:
            result_queue.put_nowait(
                TestError(subtest, 'Duplicate expectation path!'))
          else:
            if test_path is not None:
              paths_seen.add(test_path)
            name = subtest.name
            if not neg_matcher.match(name) and matcher.match(name):
              ok_tests.append(subtest)

        if ok_tests:
          seen_tests = True
          yield root_test.restrict(ok_tests)

      if not seen_tests:
        result_queue.put_nowait(NoMatchingTestsError())
    except KeyboardInterrupt:
      pass
    finally:
      for _ in xrange(opts.jobs):
        test_queue.put_nowait(None)


  next_stage = (result_queue if opts.handler.SKIP_RUNLOOP else test_queue)
  with cover_ctx:
    opts.handler.gen_stage_loop(opts, generate_tests(), next_stage.put_nowait,
                                result_queue.put_nowait)


def run_loop_process(test_queue, result_queue, opts, kill_switch, cover_ctx):
  """Consume `Test` instances from |test_queue|, run them, and yield the results
  into opts.run_stage_loop().

  Generates coverage data as a side-effect.
  @type test_queue: multiprocessing.Queue()
  @type result_queue: multiprocessing.Queue()
  @type opts: argparse.Namespace
  @type kill_switch: multiprocessing.Event()
  @type cover_ctx: cover.CoverageContext().create_subprocess_context()
  """
  logstream = ResetableStringIO()
  logger = logging.getLogger()
  logger.setLevel(logging.DEBUG)
  shandler = logging.StreamHandler(logstream)
  shandler.setFormatter(
      logging.Formatter('%(levelname)s: %(message)s'))
  logger.addHandler(shandler)

  SKIP = object()
  def process_test(subtest):
    logstream.reset()
    subresult = subtest.run()
    if isinstance(subresult, TestError):
      result_queue.put_nowait(subresult)
      return SKIP
    elif not isinstance(subresult, Result):
      result_queue.put_nowait(
          TestError(
              subtest,
              'Got non-Result instance from test: %r' % subresult))
      return SKIP
    return subresult

  def generate_tests_results():
    try:
      while not kill_switch.is_set():
        try:
          test = test_queue.get(timeout=0.1)
          if test is None:
            break
        except Queue.Empty:
          continue

        try:
          for subtest, subresult in test.process(process_test):
            if subresult is not SKIP:
              yield subtest, subresult, logstream.getvalue().splitlines()
        except Exception:
          result_queue.put_nowait(
              TestError(test, traceback.format_exc(),
                        logstream.getvalue().splitlines()))
    except KeyboardInterrupt:
      pass

  with cover_ctx:
    opts.handler.run_stage_loop(opts, generate_tests_results(),
                                result_queue.put_nowait)


def result_loop(test_gen, cover_ctx, opts):
  kill_switch = multiprocessing.Event()
  def handle_killswitch(*_):
    kill_switch.set()
    # Reset the signal to DFL so that double ctrl-C kills us for sure.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
  signal.signal(signal.SIGINT, handle_killswitch)
  signal.signal(signal.SIGTERM, handle_killswitch)

  test_queue = multiprocessing.Queue()
  result_queue = multiprocessing.Queue()

  test_gen_args = (
      test_gen, test_queue, result_queue, opts, kill_switch, cover_ctx)

  procs = []
  if opts.handler.SKIP_RUNLOOP:
    gen_loop_process(*test_gen_args)
  else:
    procs = [multiprocessing.Process(
        target=gen_loop_process, args=test_gen_args)]

    procs += [
        multiprocessing.Process(
            target=run_loop_process, args=(
                test_queue, result_queue, opts, kill_switch, cover_ctx))
        for _ in xrange(opts.jobs)
    ]

    for p in procs:
      p.daemon = True
      p.start()

  error = False
  try:
    def generate_objects():
      while not kill_switch.is_set():
        while not kill_switch.is_set():
          try:
            yield result_queue.get(timeout=0.1)
          except Queue.Empty:
            break

        if not any(p.is_alive() for p in procs):
          break

      # Get everything still in the queue. Still need timeout, but since nothing
      # is going to be adding stuff to the queue, use a very short timeout.
      while not kill_switch.is_set():
        try:
          yield result_queue.get(timeout=0.00001)
        except Queue.Empty:
          break

      if kill_switch.is_set():
        raise ResultStageAbort()
    error = opts.handler.result_stage_loop(opts, generate_objects())
  except ResultStageAbort:
    pass

  for p in procs:
    p.join()

  if not kill_switch.is_set() and not result_queue.empty():
    error = True

  return error, kill_switch.is_set()
