# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cStringIO import StringIO

import test_env  # pylint: disable=W0611

import coverage

# This is instead of a contextmanager because it causes old pylints to crash :(
class _Cover(object):
  def __init__(self, enabled, maybe_kwargs):
    self.enabled = enabled
    self.kwargs = maybe_kwargs or {}
    self.c = None

  def __call__(self, **kwargs):
    new_kwargs = self.kwargs
    if self.enabled:
      new_kwargs = new_kwargs.copy()
      new_kwargs.update(kwargs)
    return _Cover(self.enabled, new_kwargs)

  def __enter__(self):
    if self.enabled:
      if self.c is None:
        self.c = coverage.coverage(**self.kwargs)
        self.c._warn_no_data = False
      self.c.start()

  def __exit__(self, *_):
    if self.enabled:
      self.c.stop()
      self.c.save()


class CoverageContext(object):
  def __init__(self, name, cover_branches, html_report, enabled=True):
    self.opts = None
    self.cov = None
    self.enabled = enabled

    self.html_report = html_report

    if enabled:
      self.opts = {
        'data_file': '.%s_coverage' % name,
        'data_suffix': True,
        'branch': cover_branches,
      }
      self.cov = coverage.coverage(**self.opts)
      self.cov.erase()

  def cleanup(self):
    if self.enabled:
      self.cov.combine()

  def report(self, verbose):
    fail = False

    if self.enabled:
      if self.html_report:
        self.cov.html_report(directory=self.html_report)

      outf = StringIO()
      fail = self.cov.report(file=outf) != 100.0
      summary = outf.getvalue().replace('%- 15s' % 'Name', 'Coverage Report', 1)
      if verbose:
        print
        print summary
      elif fail:
        print
        lines = summary.splitlines()
        lines[2:-2] = [l for l in lines[2:-2]
                       if not l.strip().endswith('100%')]
        print '\n'.join(lines)
        print
        print 'FATAL: Test coverage is not at 100%.'

    return not fail

  def create_subprocess_context(self):
    # Can't have this method be the contextmanager because otherwise
    # self (and self.cov) will get pickled to the subprocess, and we don't want
    # that :(
    return _Cover(self.enabled, self.opts)
