#!/usr/bin/env python
# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Entry point for fully-annotated builds.

This script is part of the effort to move all builds to annotator-based
systems. Any builder configured to use the AnnotatorFactory.BaseFactory()
found in scripts/master/factory/annotator_factory.py executes a single
AddAnnotatedScript step. That step (found in annotator_commands.py) calls
this script with the build- and factory-properties passed on the command
line. In general, the factory properties will include one or more other
scripts for this script to delegate to.
"""

import json
import optparse
import os
import subprocess
import sys

from common import annotator
from common import chromium_utils


SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))


def get_args():
  """Process command-line arguments."""

  parser = optparse.OptionParser(
      description='Entry point for annotated builds.')
  parser.add_option('--build-properties',
                    action='callback', callback=chromium_utils.convert_json,
                    type='string', default={},
                    help='build properties in JSON format')
  parser.add_option('--factory-properties',
                    action='callback', callback=chromium_utils.convert_json,
                    type='string', default={},
                    help='factory properties in JSON format')
  parser.add_option('--output-build-properties', action='store_true',
                    help='output JSON-encoded build properties extracted from'
                    ' the build')
  parser.add_option('--output-factory-properties', action='store_true',
                    help='output JSON-encoded factory properties extracted from'
                    'the build factory')
  return parser.parse_args()


def main():
  opts, _ = get_args()

  seed_steps = ['setup_build']
  if 'checkout' in opts.factory_properties:
    seed_steps.append('checkout')
  stream = annotator.StructuredAnnotationStream(seed_steps=seed_steps)

  # Supplement the master-supplied factory_properties dictionary with the values
  # found in the slave-side recipe.
  with stream.step('setup_build') as s:
    assert 'recipe' in opts.factory_properties
    factory_properties = opts.factory_properties
    recipe = factory_properties['recipe'] + '.py'
    recipe_dirs = (os.path.abspath(p) for p in (
        os.path.join(SCRIPT_PATH, '..', '..', '..', 'build_internal', 'scripts',
                     'slave-internal', 'recipes'),
        os.path.join(SCRIPT_PATH, '..', '..', '..', 'build_internal', 'scripts',
                     'slave', 'recipes'),
        os.path.join(SCRIPT_PATH, 'recipes'),
    ))
    recipe_dirs = [os.path.abspath(p) for p in recipe_dirs]
    for path in recipe_dirs:
      recipe_dict = chromium_utils.ParsePythonCfg(os.path.join(path, recipe))
      if recipe_dict:
        break
    else:
      s.step_text('recipe not found')
      s.step_failure()
      return

    factory_properties.update(recipe_dict['factory_properties'])

  # Now do the heavy lifting: handle elements of factory properties with various
  # other slave scripts.
  if 'checkout' in factory_properties:
    with stream.step('checkout'):
      checkout_type = factory_properties['checkout']
      checkout_spec = factory_properties['%s_spec' % checkout_type]
      ret = subprocess.call([sys.executable,
                             '%s/annotated_checkout.py' % SCRIPT_PATH,
                             '--type', checkout_type,
                             '--spec', json.dumps(checkout_spec)])
      if ret != 0:
        return ret

  # Execute a script if specified.
  if 'script' in factory_properties:
    script = factory_properties['script']
    cmd = [sys.executable, script,
           '--factory_properties', json.dumps(factory_properties),
           '--build_properties', json.dumps(opts.build_properties)]
    print 'in %s executing: %s' % (os.getcwd(), ' '.join(cmd))
    ret = subprocess.call(cmd)
    if ret != 0:
      return ret


def UpdateScripts():
  stream = annotator.StructuredAnnotationStream(seed_steps=['update_scripts'])
  with stream.step('update_scripts') as s:
    if os.environ.get('RUN_SLAVE_UPDATED_SCRIPTS'):
      os.environ.pop('RUN_SLAVE_UPDATED_SCRIPTS')
      return False
    gclient_name = 'gclient'
    if sys.platform.startswith('win'):
      gclient_name += '.bat'
    gclient_path = os.path.join(SCRIPT_PATH, '..', '..', '..',
                                'depot_tools', gclient_name)
    if subprocess.call([gclient_path, 'sync', '--force']) != 0:
      s.text('gclient sync failed!')
      s.step_warnings()
    os.environ['RUN_SLAVE_UPDATED_SCRIPTS'] = '1'
    return True


if __name__ == '__main__':
  if UpdateScripts():
    os.execv(sys.executable, [sys.executable] + sys.argv)
  main()
