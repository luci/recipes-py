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


def path_func(name, base):
  """Returns a shortcut function which functions like os.path.join with a
  fixed first component |base|."""
  def path_func_inner(*pieces):
    """This function returns a path to a file in '%s'."""
    return _os.path.join(base, *pieces)
  path_func_inner.__name__ = name
  path_func_inner.__doc__ = path_func_inner.__doc__ % base
  return path_func_inner


depot_tools_path = path_func('depot_tools_path', DEPOT_TOOLS_ROOT)
build_internal_path = path_func('build_internal_path', BUILD_INTERNAL_ROOT)
build_path = path_func('build_path', BUILD_ROOT)
slave_build_path = path_func('slave_build_path', SLAVE_BUILD_ROOT)


# e.g. /b/build/slave/<slave-name>/build/src
def checkout(build_properties, *pieces):
  return slave_build_path(build_properties['root'], *pieces)


class PropertyPlaceholder(object):
  """PropertyPlaceholder is meant to be a singleton object which, when added
  to a step's cmd list, will be replaced by annotator_run with
  factory-properties and build-properties after your recipe terminates.

  Note that the 'steps' key will be absent from factory-properties. If you
  need to pass the list of steps to some of the steps, you will need to do
  that manually in your recipe (preferably with json.dumps()).

  This placeholder is AUTOMATICALLY added when you use the step() function
  in this module.
  """
  pass
PropertyPlaceholder = PropertyPlaceholder()


def step(name, cmd, add_properties=True, **kwargs):
  """Returns a step dictionary which is compatible with annotator.py. Uses
  PropertyPlaceholder as a stand-in for build-properties and factory-properties
  so that annotator_run can fill them in after the recipe completes."""
  assert isinstance(cmd, list)
  if add_properties:
    cmd += [PropertyPlaceholder]
  ret = kwargs
  ret.update({'name': name, 'cmd': cmd})
  return ret


def apply_patch_step(build_properties):
  return {
    'name': 'apply_issue',
    'cmd': [
        'apply_issue',
        '-r', build_properties['root'],
        '-i', build_properties['issue'],
        '-p', build_properties['patchset'],
        '-s', build_properties['rietveld'],
        '-e', 'commit-bot@chromium.org'] }


def git_step(build_properties, cmd):
  root_path = checkout(build_properties)
  name = 'git '+cmd[0]
  # Distinguish 'git config' commands by the variable they are setting.
  if cmd[0] == 'config' and not cmd[1].startswith('-'):
    name += " "+cmd[1]
  return {
      'name': name,
      'cmd': ['git', '--work-tree', root_path,
              '--git-dir', _os.path.join(root_path, '.git')]+cmd }


def gclient_spec(build_properties):
  return {'solutions': [{
      'name' : build_properties['root'],
      'url' : build_properties['root_repo_url'],
      'deps_file' : build_properties.get('root_repo_deps_file', ''),
      'managed' : True,
      'custom_deps' : {},
      'safesync_url': '',
  }]}
