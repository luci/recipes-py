# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module holds utilities which make writing recipes easier."""

import os as _os


# e.g. /b/build/slave/<slave-name>/build
SLAVE_BUILD_ROOT = _os.path.abspath(_os.getcwd())
# e.g. /b
ROOT = _os.path.abspath(_os.path.join(SLAVE_BUILD_ROOT, _os.pardir, _os.pardir,
                                      _os.pardir, _os.pardir))
# e.g. /b/build_internal
BUILD_INTERNAL_ROOT = _os.path.join(ROOT, 'build_internal')
# e.g. /b/build
BUILD_ROOT = _os.path.join(ROOT, 'build')
# e.g. /b/depot_tools
DEPOT_TOOLS_ROOT = _os.path.join(ROOT, 'depot_tools')

def _path_method(name, base):
  """Returns a shortcut static method which functions like os.path.join with a
  fixed first component |base|."""
  def path_func_inner(*pieces):
    """This function returns a path to a file in '%s'."""
    return _os.path.join(base, *pieces)
  path_func_inner.__name__ = name
  path_func_inner.__doc__ = path_func_inner.__doc__ % base
  return path_func_inner

# Recipes are expected to use each of these functions to generate paths for
# use in annotator steps. See the documentation for _path_method.
depot_tools_path = _path_method('depot_tools_path', DEPOT_TOOLS_ROOT)
build_internal_path = _path_method('build_internal_path', BUILD_INTERNAL_ROOT)
build_path = _path_method('build_path', BUILD_ROOT)
slave_build_path = _path_method('slave_build_path', SLAVE_BUILD_ROOT)

def checkout_path(*pieces):
  """This function returns the equivalent of a path to a file in checkout root.
  It is not a 'real' path because it contains a string token which must be
  filled in by annotator_run.

  Example (assuming that the checkout is a standard chromium checkout in 'src'):
    checkout_path('foobar')
      returns:
    "%(CheckoutRootPlaceholder)s/foobar"
      which, when run under annotator_run.py becomes:
    "/b/build/slave/win_rel/build/src/foobar"

  The actual checkout root is filled in by annotated_run after the recipe
  completes, and is dependent on the implementation of 'root()' in
  annotated_checkout for the checkout type that you've selected.

  NOTE: In order for this function to work, your recipe MUST use the 'checkout'
  functionality provided by annotated_run.
  """
  return _os.path.join("%(CheckoutRootPlaceholder)s", *pieces)


class PropertyPlaceholder(object):
  """PropertyPlaceholder is meant to be a singleton object which, when added
  to a step's cmd list, will be replaced by annotated_run with the command
  parameters --factory-properties={...} and --build-properties={...} after
  your recipe terminates.

  Note that the 'steps' key will be absent from factory-properties. If you
  need to pass the list of steps to some of the steps, you will need to do
  that manually in your recipe (preferably with json.dumps()).

  This placeholder can be automatically added when you use the Steps.step()
  method in this module.
  """
  pass
PropertyPlaceholder = PropertyPlaceholder()


class Steps(object):
  """Provides methods to build steps that annotator.py understands."""

  def __init__(self, build_properties):
    self.build_properties = build_properties

  def gclient_spec(self):
    """Returns default gclient spec. Constructs it from build_properties."""
    return {'solutions': [{
        'name' : self.build_properties['root'],
        'url' : self.build_properties['root_repo_url'],
        'deps_file' : self.build_properties.get('root_repo_deps_file', ''),
        'managed' : True,
        'custom_deps' : {},
        'safesync_url': '',
    }]}

  @staticmethod
  def step(name, cmd, add_properties=False, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py. Uses
    PropertyPlaceholder as a stand-in for build-properties and
    factory-properties so that annotated_run can fill them in after the recipe
    completes."""
    assert isinstance(cmd, list)
    if add_properties:
      cmd += [PropertyPlaceholder]
    ret = kwargs
    ret.update({'name': name, 'cmd': cmd})
    return ret

  def apply_patch_step(self):
    return self.step('apply_issue', [
        depot_tools_path('apply_issue'),
        '-r', checkout_path(),
        '-i', self.build_properties['issue'],
        '-p', self.build_properties['patchset'],
        '-s', self.build_properties['rietveld'],
        '-e', 'commit-bot@chromium.org'])

  def git_step(self, *args):
    name = 'git '+args[0]
    # Distinguish 'git config' commands by the variable they are setting.
    if args[0] == 'config' and not args[1].startswith('-'):
      name += " "+args[1]
    return self.step(name, [
        'git', '--work-tree', checkout_path(),
               '--git-dir', checkout_path('.git')]+list(args))
