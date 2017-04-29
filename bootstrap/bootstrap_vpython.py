#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import argparse
import logging
import os
import subprocess
import sys

LOGGER = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == 'win32'
EXE_EXTENSION = '.bat' if IS_WINDOWS else ''

# /path/to/recipes-py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIPD_ROOT = os.path.join(ROOT, '.cipd_root')

VPYTHON_PACKAGE = 'infra/tools/luci/vpython/${platform}'
VPYTHON_VERSION = 'git_revision:ea5f3c7c274276673049e6bc2fa2619b1f55d589'


def _ensure_vpython(cipd_root):
  manifest = '%s %s' % (VPYTHON_PACKAGE, VPYTHON_VERSION)

  cipd_bin = 'cipd' + EXE_EXTENSION
  cmd = [cipd_bin, 'ensure', '-root', cipd_root, '-ensure-file=-']

  LOGGER.debug('Running CIPD ensure command (cwd=%s): %s', os.getcwd(), cmd)
  proc = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
  )
  stdout, _ = proc.communicate(input=manifest)
  if proc.returncode != 0:
    raise ValueError('Failed to install CIPD manifest (%d):\n%s' % (
        proc.returncode, stdout,))
  vpython_path = os.path.join(cipd_root, 'vpython' + EXE_EXTENSION)
  if not os.path.isfile(vpython_path):
    raise ValueError('`vpython` not found at [%s]' % (vpython_path,))
  return vpython_path


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('--venv-spec', metavar='PATH',
      default=os.path.join(ROOT, 'bootstrap', 'venv.cfg'),
      help='Path to vpython enviornment specification file to use (default '
           'is %(default)s).')
  parser.add_argument('--vpython-path', metavar='PATH',
      help='Use "vpython" binary at PATH, instead of the bootstrap default.')
  parser.add_argument('-v', '--verbose', action='count', default=0,
      help='Increase verbosity. Can be specified multiple times.')
  parser.add_argument('--presubmit', action='store_true',
      help='Run PRESUBMIT check and exit, zero on success, non-zero on '
           'failure.')
  parser.add_argument('args', nargs='*',
      help='Flags and arguments to pass to the target Python script.')
  opts = parser.parse_args(args)

  if opts.verbose >= 2:
    log_level = logging.DEBUG
    vpython_log_level = 'debug'
  elif opts.verbose == 1:
    log_level = logging.INFO
    vpython_log_level = 'info'
  else:
    log_level = logging.WARNING
    vpython_log_level = 'warning'
  logging.getLogger().setLevel(log_level)

  vpython_path = opts.vpython_path
  if not vpython_path:
    vpython_path = _ensure_vpython(CIPD_ROOT)

  vpython_args = [vpython_path]
  if vpython_log_level:
    vpython_args += ['-log-level', vpython_log_level]
  if opts.venv_spec:
    vpython_args += ['-spec', opts.venv_spec]

  # If we're configured for PRESUBMIT, run the presubmit command and quit.
  if opts.presubmit:
    vpython_args += ['-dev', 'verify']
    return subprocess.call(vpython_args)

  vpython_args += ['--'] + opts.args
  LOGGER.debug('Executing bootstrapped Python: %s', vpython_args)
  return subprocess.call(vpython_args)


if __name__ == '__main__':
  logging.basicConfig()
  sys.exit(main(sys.argv[1:]))
