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

  def __enter__(self):
    if self.enabled:
      self.c = coverage.coverage(**self.kwargs)
      self.c._warn_no_data = False
      self.c.start()

  def __exit__(self, *_):
    if self.enabled:
      self.c.stop()
      self.c.save()


class CoverageContext(object):
  def __init__(self, name, includes, omits, cover_branches, html_report,
               extra_coverage_data, enabled=True):
    self.opts = None
    self.cov = None
    self.enabled = enabled

    self.html_report = html_report
    self.extra_data = extra_coverage_data or ()

    if enabled:
      self.opts = {
        'include': includes,
        'omit': omits,
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
      include_files = set()
      for datafile in self.extra_data:
        # pylint: disable=W0212
        lines, arcs = self.cov.data._read_file(datafile)
        self.cov.data.add_line_data(lines)
        self.cov.data.add_arc_data(arcs)
        include_files.update(lines)
        include_files.update(arcs)

      self.cov.config.include = list(
          set(self.cov.config.include) | include_files)

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
