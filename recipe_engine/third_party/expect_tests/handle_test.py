# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import os
import sys
import time

from cStringIO import StringIO

from .type_definitions import DirSeen, Handler, Failure
from .serialize import GetCurrentData, DiffData, NonExistant


Missing = collections.namedtuple('Missing', 'test log_lines')
Fail = collections.namedtuple('Fail', 'test diff log_lines')
Pass = collections.namedtuple('Pass', 'test')


class TestHandler(Handler):
  """Run the tests."""

  @classmethod
  def gen_stage_loop(cls, _opts, tests, put_next_stage, put_result_stage):
    dirs_seen = set()
    for test in tests:
      subtests = test.tests
      for subtest in subtests:
        if subtest.expect_dir not in dirs_seen:
          put_result_stage(DirSeen(subtest.expect_dir))
          dirs_seen.add(subtest.expect_dir)
      put_next_stage(test)

  @classmethod
  def run_stage_loop(cls, _opts, results, put_next_stage):
    for test, result, log_lines in results:
      current, _ = GetCurrentData(test)
      if current is NonExistant:
        put_next_stage(Missing(test, log_lines))
      else:
        diff = DiffData(current, result.data)
        if not diff:
          put_next_stage(Pass(test))
        else:
          put_next_stage(Fail(test, diff, log_lines))

  class ResultStageHandler(Handler.ResultStageHandler):
    def __init__(self, *args):
      super(TestHandler.ResultStageHandler, self).__init__(*args)
      self.dirs_seen = set()
      self.files_expected = collections.defaultdict(set)
      self.err_out = StringIO()
      self.start = time.time()
      self.errors = collections.defaultdict(int)
      self.num_tests = 0

    def _emit(self, short, test, verbose):
      if self.opts.verbose:
        print >> sys.stdout, '%s ... %s' % (test.name if test else '????',
                                            verbose)
      else:
        sys.stdout.write(short)
        sys.stdout.flush()

    def _add_result(self, msg, test, header, category, log_lines=()):
      print >> self.err_out
      print >> self.err_out, '=' * 70
      if test is not None:
        print >> self.err_out, '%s: %s (%s)' % (
            header, test.name, test.expect_path())
      print >> self.err_out, '-' * 70
      if msg:
        print >> self.err_out, msg
      if log_lines:
        print >> self.err_out, '==== captured logging output ===='
        print >> self.err_out, '\n'.join(log_lines)
      self.errors[category] += 1
      self.num_tests += 1

    def handle_DirSeen(self, dirseen):
      self.dirs_seen.add(dirseen.dir)

    def _handle_record(self, test):
      self.num_tests += 1
      if test.expect_path() is not None:
        head, tail = os.path.split(test.expect_path())
        self.files_expected[head].add(tail)

    def handle_Pass(self, p):
      self._handle_record(p.test)
      if not self.opts.quiet:
        self._emit('.', p.test, 'ok')

    def handle_Fail(self, fail):
      self._handle_record(fail.test)
      self._emit('F', fail.test, 'FAIL')
      self._add_result('\n'.join(fail.diff), fail.test, 'FAIL', 'failures',
                       fail.log_lines)
      return Failure()

    def handle_TestError(self, test_error):
      self._handle_record(test_error.test)
      self._emit('E', test_error.test, 'ERROR')
      self._add_result(test_error.message, test_error.test, 'ERROR', 'errors',
                       test_error.log_lines)
      return Failure()

    def handle_UnknownError(self, error):
      self._handle_record(error.test)
      self._emit('U', None, 'UNKNOWN ERROR')
      self._add_result(error.message, None, 'UNKNOWN ERROR', 'unknown_errors')
      return Failure()

    def handle_Missing(self, missing):
      self._handle_record(missing.test)
      self._emit('M', missing.test, 'MISSING')
      self._add_result('', missing.test, 'MISSING', 'missing',
                       missing.log_lines)
      return Failure()

    def finalize(self, aborted):
      # TODO(iannucci): print summary stats (and timing info?)
      if not aborted and not self.opts.test_glob:
        for d in self.dirs_seen:
          expected = self.files_expected[d]
          for f in os.listdir(d):
            # Skip OWNERS files and files beginning with a '.' (like '.svn')
            if f == 'OWNERS' or f[0] == '.':
              continue
            if f not in expected:
              path = os.path.join(d, f)
              self._add_result('Unexpected file %s' % path, None, 'UNEXPECTED',
                               'unexpected_file')

      buf = self.err_out.getvalue()
      if buf:
        print
        print buf
      if not self.opts.quiet:
        print
        print '-' * 70
        print 'Ran %d tests in %0.3fs' % (
            self.num_tests, time.time() - self.start)
        print
      if aborted:
        print 'ABORTED'
      elif self.errors:
        print 'FAILED (%s)' % (', '.join('%s=%d' % i
                                         for i in self.errors.iteritems()))
      elif not self.opts.quiet:
        print 'OK'

