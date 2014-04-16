# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script to setup the environment to run unit tests.

Modifies PYTHONPATH to automatically include parent, common and pylibs
directories.
"""

import os
import sys
import textwrap

RUNTESTS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(RUNTESTS_DIR, 'data')
BASE_DIR = os.path.abspath(os.path.join(RUNTESTS_DIR, '..', '..', '..'))
DEPOT_TOOLS_DIR = os.path.join(BASE_DIR, os.pardir, 'depot_tools')

sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
sys.path.insert(0, os.path.join(BASE_DIR, 'site_config'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'buildbot_slave_8_4'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'twisted_10_2'))
sys.path.insert(0, os.path.join(BASE_DIR, 'third_party', 'mock-1.0.1'))

def ensure_coverage_importable():
  try:
    from distutils.version import StrictVersion
    import coverage
    if (StrictVersion(coverage.__version__) < StrictVersion('3.7') or
        not coverage.collector.CTracer):
      del sys.modules['coverage']
      del coverage
    else:
      return
  except ImportError:
    if sys.platform.startswith('win'):
      # In order to compile the coverage module on Windows we need to set the
      # 'VS90COMNTOOLS' environment variable. This usually point to the
      # installation folder of VS2008 but we can fake it to make it point to the
      # version of the toolchain checked in depot_tools.
      #
      # This variable usually point to the $(VsInstallDir)\Common7\Tools but is
      # only used to access %VS90COMNTOOLS%/../../VC/vcvarsall.bat and therefore
      # any valid directory respecting this structure can be used.
      vc_path = os.path.join(DEPOT_TOOLS_DIR, 'win_toolchain', 'vs2013_files',
          'VC', 'bin')
      # If the toolchain isn't available then ask the user to fetch chromium in
      # order to install it.
      if not os.path.isdir(vc_path):
        print textwrap.dedent("""
        You probably don't have the Windows toolchain in your depot_tools
        checkout. Install it by running:
          fetch chromium
        """)
        sys.exit(1)
      os.environ['VS90COMNTOOLS'] = vc_path

  try:
    import setuptools  # pylint: disable=W0612
  except ImportError:
    print textwrap.dedent("""
    No compatible system-wide python-coverage package installed, and
    setuptools is not installed either. Please obtain setuptools by:

    Debian/Ubuntu:
      sudo apt-get install python-setuptools python-dev

    OS X:
      https://pypi.python.org/pypi/setuptools#unix-including-mac-os-x-curl

    Other:
      https://pypi.python.org/pypi/setuptools#installation-instructions
    """)
    sys.exit(1)

  from pkg_resources import get_build_platform
  try:
    # Python 2.7 or >= 3.2
    from sysconfig import get_python_version
  except ImportError:
    from distutils.sysconfig import get_python_version

  cov_dir = os.path.join(BASE_DIR, 'third_party', 'coverage-3.7.1')
  cov_egg = os.path.join(cov_dir, 'dist', 'coverage-3.7.1-py%s-%s.egg' % (
      get_python_version(), get_build_platform()))

  # The C-compiled coverage engine is WAY faster (and less buggy) than the pure
  # python version, so we build the dist_egg if necessary.
  if not os.path.exists(cov_egg):
    import subprocess
    print 'Building Coverage 3.7.1'
    p = subprocess.Popen([sys.executable, 'setup.py', 'bdist_egg'], cwd=cov_dir,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
      print 'Error while building :('
      print stdout
      print stderr
      if sys.platform.startswith('linux'):
        print textwrap.dedent("""
        You probably don't have the 'python-dev' package installed. Install
        it by running:
          sudo apt-get install python-dev
        """)
      else:
        print textwrap.dedent("""
        I'm not sure what's wrong, but your system seems incapable of building
        python extensions. Please fix that by installing a Python with headers
        and the approprite command-line build tools for your platform.
        """)
      sys.exit(1)

  sys.path.insert(0, cov_egg)

ensure_coverage_importable()

from common import find_depot_tools  # pylint: disable=W0611
