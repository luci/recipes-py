# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import os
import sys
import time

from .type_definitions import Handler
from .serialize import WriteNewData, DiffData, NonExistant, GetCurrentData


DirSeen = collections.namedtuple('DirSeen', 'dir')
ForcedWriteAction = collections.namedtuple('ForcedWriteAction', 'test')
DiffWriteAction = collections.namedtuple('DiffWriteAction', 'test')
SchemaDiffWriteAction = collections.namedtuple('SchemaDiffWriteAction', 'test')
MissingWriteAction = collections.namedtuple('MissingWriteAction', 'test')
NoAction = collections.namedtuple('NoAction', 'test')


class TrainHandler(Handler):
  """Write test expectations to disk."""
  @classmethod
  def add_options(cls, parser):
    parser.add_argument(
        '--force', action='store_true', help=(
            'Immediately write expectations to disk instead of determining if '
            'they contain a diff from the current expectations.'
        ))

  @classmethod
  def gen_stage_loop(cls, _opts, tests, put_next_stage, put_result_stage):
    dirs_seen = set()
    for test in tests:
      if test.expect_dir not in dirs_seen:
        try:
          os.makedirs(test.expect_dir)
        except OSError:
          pass
        put_result_stage(DirSeen(test.expect_dir))
        dirs_seen.add(test.expect_dir)
      put_next_stage(test)

  @classmethod
  def run_stage_loop(cls, opts, tests_results, put_next_stage):
    for test, result in tests_results:
      if opts.force:
        WriteNewData(test, result.data)
        put_next_stage(ForcedWriteAction(test))
        continue

      current, same_schema = GetCurrentData(test)
      diff = DiffData(current, result.data)
      if diff is not None or not same_schema:
        WriteNewData(test, result.data)
        if current is NonExistant:
          put_next_stage(MissingWriteAction(test))
        elif diff:
          put_next_stage(DiffWriteAction(test))
        else:
          put_next_stage(SchemaDiffWriteAction(test))
      else:
        put_next_stage(NoAction(test))

  class ResultStageHandler(Handler.ResultStageHandler):
    def __init__(self, opts):
      super(TrainHandler.ResultStageHandler, self).__init__(opts)
      self.dirs_seen = set()
      self.files_expected = collections.defaultdict(set)
      self.start = time.time()
      self.num_tests = 0
      self.verbose_actions = []
      self.normal_actions = []

    def _record_expected(self, test, indicator):
      if not self.opts.quiet:
        sys.stdout.write(indicator)
        sys.stdout.flush()
      head, tail = os.path.split(test.expect_path())
      self.files_expected[head].add(tail)

    def _record_write(self, test, indicator, why):
      self._record_expected(test, indicator)
      name = test.expect_path() if self.opts.verbose else test.name
      self.normal_actions.append('Wrote %s: %s' % (name, why))

    def handle_DirSeen(self, dirseen):
      self.dirs_seen.add(dirseen.dir)

    def handle_NoAction(self, result):
      self._record_expected(result.test, '.')
      self.verbose_actions.append('%s did not change' % result.test.name)

    def handle_ForcedWriteAction(self, result):
      self._record_write(result.test, 'F', 'forced')

    def handle_DiffWriteAction(self, result):
      self._record_write(result.test, 'D', 'diff')

    def handle_SchemaDiffWriteAction(self, result):
      self._record_write(result.test, 'S', 'schema changed')

    def handle_MissingWriteAction(self, result):
      self._record_write(result.test, 'M', 'missing')

    def handle_TestError(self, result):
      self._record_expected(result.test, 'E')
      self.normal_actions.append('%s failed: %s' %
                                 (result.test.name, result.message))

    def finalize(self, aborted):
      super(TrainHandler.ResultStageHandler, self).finalize(aborted)

      if not aborted and not self.opts.test_glob:
        for d in self.dirs_seen:
          expected = self.files_expected[d]
          for f in os.listdir(d):
            if f == 'OWNERS':
              continue
            if f not in expected:
              path = os.path.join(d, f)
              os.unlink(path)
              if self.opts.verbose:
                print 'Removed unexpected file', path

      if not self.opts.quiet:
        print

        if self.normal_actions:
          print '\n'.join(self.normal_actions)
        if self.opts.verbose:
          if self.verbose_actions:
            print '\n'.join(self.verbose_actions)

        num_tests = sum(len(x) for x in self.files_expected.itervalues())
        print '-' * 70
        print 'Trained %d tests in %0.3fs' % (
            num_tests, time.time() - self.start)



