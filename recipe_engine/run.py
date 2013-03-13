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

The main mode of operation is for factory_properties to contain a single
property 'recipe' whose value is the basename (without extension) of a python
script in one of the following locations (looked up in this order):
  * build_internal/scripts/slave-internal/recipes
  * build_internal/scripts/slave/recipes
  * build/scripts/slave/recipes

For example, these factory_properties would run the 'run_presubmit' recipe
located in build/scripts/slave/recipes:
    { 'recipe': 'run_presubmit' }

Annotated_run.py will then import the recipe and expect to call a function whose
signature is GetFactoryProperties(build_properties) -> factory_properties. The
returned factory_properties will then be used to execute the following actions:
  * optional 'checkout'
    * This checks out a gclient/git/svn spec into the slave build dir.
    * The value of checkout is expected to be in ('gclient', 'git', 'svn')
    * If checkout is specified, annotated_run will also expect to find a value
      for ('%s_spec' % checkout), e.g. 'gclient_spec'. The value of this spec
      is defined by build/scripts/slave/annotated_checkout.py.
  * 'script' or 'steps'
    * 'script' allows you to specify a single script which will be invoked with
      build-properties and factory-properties.
    * 'steps' serves as input for build/scripts/common/annotator.py
      * You can have annotated_run pass build/factory properties to a step by
        using the recipe_util.step() function.
"""

import contextlib
import json
import optparse
import os
import subprocess
import sys
import tempfile

from common import annotator
from common import chromium_utils
from slave import recipe_util

SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))


@contextlib.contextmanager
def temp_import_path(path):
  added = False
  if path not in sys.path:
    sys.path.insert(0, path)
    added = True
  try:
    yield
  finally:
    if added and path in sys.path:
      sys.path.remove(path)


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

  # Supplement the master-supplied factory_properties dictionary with the values
  # found in the slave-side recipe.
  stream = annotator.StructuredAnnotationStream(seed_steps=['setup_build'])
  with stream.step('setup_build') as s:
    assert 'recipe' in opts.factory_properties
    factory_properties = opts.factory_properties
    recipe = factory_properties['recipe']
    recipe_dirs = (os.path.abspath(p) for p in (
        os.path.join(SCRIPT_PATH, '..', '..', '..', 'build_internal', 'scripts',
                     'slave-internal', 'recipes'),
        os.path.join(SCRIPT_PATH, '..', '..', '..', 'build_internal', 'scripts',
                     'slave', 'recipes'),
        os.path.join(SCRIPT_PATH, 'recipes'),
    ))
    recipe_dirs = [os.path.abspath(p) for p in recipe_dirs]

    for path in recipe_dirs:
      recipe_module = None
      with temp_import_path(path):
        try:
          recipe_module = __import__(recipe, globals(), locals())
        except ImportError:
          continue
      recipe_dict = recipe_module.GetFactoryProperties(
          opts.build_properties.copy())
      break
    else:
      s.step_text('recipe not found')
      s.step_failure()
      return 1

    factory_properties.update(recipe_dict)

  # Now do the heavy lifting: handle elements of factory properties with various
  # other slave scripts.
  if 'checkout' in factory_properties:
    checkout_type = factory_properties['checkout']
    checkout_spec = factory_properties['%s_spec' % checkout_type]
    ret = subprocess.call([sys.executable,
                           '%s/annotated_checkout.py' % SCRIPT_PATH,
                           '--type', checkout_type,
                           '--spec', json.dumps(checkout_spec)])
    if ret != 0:
      return ret

  assert ('script' in factory_properties) or ('steps' in factory_properties)
  ret = 0

  # Execute a script if specified.
  if 'script' in factory_properties:
    script = factory_properties['script']
    cmd = [sys.executable, script,
           '--factory-properties', json.dumps(factory_properties),
           '--build-properties', json.dumps(opts.build_properties)]
    print 'in %s executing: %s' % (os.getcwd(), ' '.join(cmd))
    ret = subprocess.call(cmd)

  # Execute annotator.py with steps if specified.
  if 'steps' in factory_properties:
    steps = factory_properties.pop('steps')
    factory_properties_str = json.dumps(factory_properties)
    build_properties_str = json.dumps(opts.build_properties)
    for step in steps:
      if recipe_util.PropertyPlaceholder in step['cmd']:
        idx = step['cmd'].index(recipe_util.PropertyPlaceholder)
        step['cmd'][idx:idx+1] = [
            '--factory-properties', factory_properties_str,
            '--build-properties', build_properties_str]
    annotator_path = os.path.join(
      os.path.dirname(SCRIPT_PATH), 'common', 'annotator.py')
    tmpfile, tmpname = tempfile.mkstemp()
    try:
      cmd = [sys.executable, annotator_path, tmpname]
      step_doc = json.dumps(steps)
      with os.fdopen(tmpfile, 'wb') as f:
        f.write(step_doc)
      with stream.step('annotator_preamble') as s:
        print 'in %s executing: %s' % (os.getcwd(), ' '.join(cmd))
        print 'with: %s' % step_doc
      ret = subprocess.call(cmd)
    finally:
      os.unlink(tmpname)

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
      s.step_text('gclient sync failed!')
      s.step_warnings()
    os.environ['RUN_SLAVE_UPDATED_SCRIPTS'] = '1'
    return True


if __name__ == '__main__':
  if UpdateScripts():
    os.execv(sys.executable, [sys.executable] + sys.argv)
  sys.exit(main())
