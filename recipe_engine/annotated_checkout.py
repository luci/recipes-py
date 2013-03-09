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
import pipes

from common import annotator
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


class Checkout(object):
  def __init__(self, spec):
    self.spec = spec

  def clean(self):
    pass

  def checkout(self):
    pass


class GclientCheckout(Checkout):

  gclient_path = os.path.abspath(
    os.path.join(SCRIPT_PATH, '..', '..', '..', 'depot_tools', 'gclient'))
  if sys.platform.startswith('win'):
    gclient_path += '.bat'

  def __init__(self, *args, **kwargs):
    super(GclientCheckout, self).__init__(*args, **kwargs)
    assert 'solutions' in self.spec
    spec_string = ''
    for key in self.spec:
      # We should be using json.dumps here, but gclient directly execs the dict
      # that it receives as the argument to --spec, so we have to have True,
      # False, and None instead of JSON's true, false, and null.
      spec_string += '%s = %s\n' % (key, str(self.spec[key]))
    self.run_gclient('config', '--spec', spec_string)

  @classmethod
  def run_gclient(cls, *cmd):
    print 'Running: gclient %s' % " ".join(pipes.quote(x) for x in cmd)
    subprocess.check_call((cls.gclient_path,)+cmd)

  def clean(self):
    self.run_gclient('revert', '--nohooks')

  def checkout(self):
    self.run_gclient('sync', '--nohooks')


class GitCheckout(Checkout):
  pass


class SvnCheckout(Checkout):
  pass


def main():
  opts, _ = get_args()

  stream = annotator.StructuredAnnotationStream(
      seed_steps=['checkout_setup', 'clean', 'checkout'])
  with stream.step('checkout_setup') as s:
    class_ = globals().get('%sCheckout' % opts.type.capitalize())
    if not class_ or not issubclass(class_, Checkout):
      s.step_text('unrecognized repo type')
      s.step_failure()
      return 1
    checkout = class_(opts.spec)
  with stream.step('clean') as s:
    checkout.clean()
  with stream.step('checkout') as s:
    checkout.checkout()


if __name__ == '__main__':
  main()
