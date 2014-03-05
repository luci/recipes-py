# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script to setup the environment to run unit tests.

Modifies PYTHONPATH to automatically include parent, common and pylibs
directories.
"""

import os
import sys

RUNTESTS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(RUNTESTS_DIR, 'data')
BASE_DIR = os.path.abspath(os.path.join(RUNTESTS_DIR, '..', '..', '..'))

sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
sys.path.insert(0, os.path.join(BASE_DIR, 'site_config'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'buildbot_slave_8_4'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'twisted_10_2'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'mock-1.0.1'))

try:
  # The C-compiled coverage engine is WAY faster than the pure python version.
  # If we have it, then don't bother with the pure python one.
  import coverage
except ImportError:
  sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'coverage-3.6'))
  import coverage

def print_coverage_warning():
  if not hasattr(coverage.collector, 'CTracer'):
    print "WARNING: Using the pure-python coverage module."
    print "         Install the native python coverage module to speed recipe"
    print "         training up by an order of magnitude."
    print
    print "           pip install coverage"
    print "         OR"
    print "           easy_install coverage"

from common import find_depot_tools  # pylint: disable=W0611
