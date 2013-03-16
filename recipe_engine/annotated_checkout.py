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


class _CheckoutMetaclass(type):
  """Automatically register Checkout subclasses for factory discoverability."""
  checkout_registry = {}

  def __new__(mcs, name, bases, attrs):
    checkout_type = attrs['CHECKOUT_TYPE']

    if checkout_type in mcs.checkout_registry:
      raise ValueError('Duplicate checkout identifier "%s" found in: %s' %
                       (checkout_type, name))

    # Only the base class is allowed to have no CHECKOUT_TYPE. The base class
    # should be the only one to specify this metaclass.
    if not checkout_type and attrs.get('__metaclass__') != mcs:
      raise ValueError('"%s" CHECKOUT_TYPE cannot be empty or None.' % name)

    newcls = super(_CheckoutMetaclass, mcs).__new__(mcs, name, bases, attrs)
    # Don't register the base class.
    if checkout_type:
      mcs.checkout_registry[checkout_type] = newcls
    return newcls


class Checkout(object):
  """Base class for implementing different types of checkouts.

  Attributes:
    CHECKOUT_TYPE: String identifier used when selecting the type of checkout to
        perform. All subclasses must specify a unique CHECKOUT_TYPE value.
  """
  __metaclass__ = _CheckoutMetaclass
  CHECKOUT_TYPE = None

  def __init__(self, spec):
    self.spec = spec

  def clean(self):
    pass

  def checkout(self):
    pass


def CheckoutFactory(type_name, spec):
  """Factory to build Checkout class instances."""
  class_ = _CheckoutMetaclass.checkout_registry.get(type_name)
  if not class_ or not issubclass(class_, Checkout):
    raise KeyError('unrecognized checkout type: %s' % type_name)
  return class_(spec)


class GclientCheckout(Checkout):
  CHECKOUT_TYPE = 'gclient'

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
  CHECKOUT_TYPE = 'git'


class SvnCheckout(Checkout):
  CHECKOUT_TYPE = 'svn'


def run(checkout_type, checkout_spec):
  """Perform a checkout with the given type and configuration.

    Args:
      checkout_type: Type of checkout to perform (matching a Checkout subclass
          CHECKOUT_TYPE attribute).
      checkout_spec: Configuration values needed for the type of checkout
          (repository url, etc.).
  """
  stream = annotator.StructuredAnnotationStream(
      seed_steps=['checkout_setup', 'clean', 'checkout'])
  with stream.step('checkout_setup') as s:
    try:
      checkout = CheckoutFactory(checkout_type, checkout_spec)
    except KeyError as e:
      s.step_text(e)
      s.step_failure()
      return 1
  with stream.step('clean') as s:
    checkout.clean()
  with stream.step('checkout') as s:
    checkout.checkout()


def main():
  opts, _ = get_args()
  return run(opts.type, opts.spec)


if __name__ == '__main__':
  sys.exit(main())
