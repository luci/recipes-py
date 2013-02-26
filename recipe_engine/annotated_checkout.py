#!/usr/bin/env python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helper script for fully-annotated builds. Performs checkouts of various
kinds.

This script is part of the effort to move all builds to annotator-based systems.
Any builder configured to use the AnnotatorFactory uses run.py as its entry
point. If that builder's factory_properties include a spec for a checkout, then
the work of actually performing that checkout is done here.
"""

import optparse
import os
import subprocess
import sys

from common import chromium_utils


SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))


def get_args():
  """Process command-line arguments."""
  parser = optparse.OptionParser(
      description='Checkout helper for annotated builds.')
  parser.add_option('--type',
                    action='store', type='string', default='',
                    help='type of checkout (i.e. gclient, git, or svn)')
  parser.add_option('--spec',
                    action='callback', callback=chromium_utils.convert_json,
                    type='string', default={},
                    help='repository spec (url and metadata) to checkout')
  return parser.parse_args()


def gclient_checkout(spec):
  """Pass a gclient spec to gclient to perform the checkout."""
  assert 'solutions' in spec
  gclient_path = os.path.join(SCRIPT_PATH, '..', '..', '..',
                              'depot_tools', 'gclient')
  if sys.platform.startswith('win'):
    gclient_path += '.bat'
  spec_string = ''
  for key in spec:
    # We should be using json.dumps here, but gclient directly execs the dict
    # that it receives as the argument to --spec, so we have to have True,
    # False, and None instead of JSON's true, false, and null.
    spec_string += '%s = %s\n' % (key, str(spec[key]))
  return subprocess.call([gclient_path, 'sync', '--spec', spec_string])


def git_checkout(spec):
  return 0


def svn_checkout(spec):
  return 0


def main():
  opts, _ = get_args()
  # Supplement the master-supplied factory_properties dictionary with the values
  # found in the slave-side recipe.
  print('@@@BUILD_STEP checkout@@@')
  if opts.type == 'gclient':
    ret = gclient_checkout(opts.spec)
  elif opts.type == 'git':
    ret = git_checkout(opts.spec)
  elif opts.type == 'svn':
    ret = svn_checkout(opts.spec)
  else:
    print('@@@STEP_TEXT@unrecognized repo type@@@')
    print('@@@STEP_FAILURE@@@')
    return 1
  if ret != 0:
    print ('@@@STEP_FAILURE@@@')
    return ret


if __name__ == '__main__':
  main()
