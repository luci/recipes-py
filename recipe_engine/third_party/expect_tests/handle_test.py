# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
import time
import collections

from cStringIO import StringIO

from .type_definitions import Handler, Failure
from .serialize import GetCurrentData, DiffData, NonExistant


Missing = collections.namedtuple('Missing', 'test')
Fail = collections.namedtuple('Fail', 'test diff')
Pass = collections.namedtuple('Pass', 'test')


class TestHandler(Handler):
  """Run the tests."""
  @classmethod
  def run_stage_loop(cls, _opts, results, put_next_stage):
    for test, result in results:
      current, _ = GetCurrentData(test)
      if current is NonExistant:
        put_next_stage(Missing(test))
      else:
        diff = DiffData(current, result.data)
        if not diff:
          put_next_stage(Pass(test))
        else:
          put_next_stage(Fail(test, diff))

  class ResultStageHandler(Handler.ResultStageHandler):
    def __init__(self, *args):
      super(TestHandler.ResultStageHandler, self).__init__(*args)
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

    def _add_result(self, msg_lines, test, header, category):
      print >> self.err_out
      print >> self.err_out, '=' * 70
      if test is not None:
        print >> self.err_out, '%s: %s (%s)' % (
            header, test.name, test.expect_path())
      print >> self.err_out, '-' * 70
      if msg_lines:
        print >> self.err_out, '\n'.join(msg_lines)
      self.errors[category] += 1
      self.num_tests += 1

    def handle_Pass(self, p):
      if not self.opts.quiet:
        self._emit('.', p.test, 'ok')
      self.num_tests += 1

    def handle_Fail(self, fail):
      self._emit('F', fail.test, 'FAIL')
      self._add_result(fail.diff, fail.test, 'FAIL', 'failures')
      return Failure()

    def handle_TestError(self, test_error):
      self._emit('E', test_error.test, 'ERROR')
      self._add_result([test_error.message], test_error.test, 'ERROR', 'errors')
      return Failure()

    def handle_UnknownError(self, error):
      self._emit('U', None, 'UNKNOWN ERROR')
      self._add_result([error.message], None, 'UNKNOWN ERROR', 'unknown_errors')
      return Failure()

    def handle_Missing(self, missing):
      self._emit('M', missing.test, 'MISSING')
      self._add_result([], missing.test, 'MISSING', 'missing')
      return Failure()

    def finalize(self, aborted):
      # TODO(iannucci): print summary stats (and timing info?)
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

