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
    assert _os.pardir not in pieces
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
"""  # pylint: disable=W0105
checkout_path = _path_method('checkout_path', "%(CheckoutRootPlaceholder)s")


def deep_set(obj, key_vals):
  """Take an object (a dict or list), and a list of key/value pairs to set,
  and transform it by replacing items in obj at the key locations with the
  respective values.

  keys are strings in the form of: (str|int)[.(str|int)]*

  Example:
    obj = {'some': {'deep': {'list': [1, 2, 3, 4, 5, 6]}}}
    key_vals = [("some.deep.list.3", 'foobar')]
    result = {'some': {'deep': {'list': [1, 2, 3, 'foobar', 5, 6]}}}
  """
  def try_int(x):
    try:
      x = int(x)
    except ValueError:
      pass
    return x

  for key, val in key_vals:
    cur_obj = obj
    components = key.split('.')
    for item in components[:-1]:
      cur_obj = cur_obj[try_int(item)]
    cur_obj[try_int(components[-1])] = val
  return obj


# This dict is used by _url_method. It contains a list of common base source
# control urls and their mirror urls. The format of the dict is:
#   { 'NamedUrl': ('<real url>', '<mirror url>'),
#     'OtherNamedUrl': ('<real url>',) }
SOURCE_URLS = {
  'ChromiumSvnURL': ('https://src.chromium.org',
                     'svn://svn-mirror.golo.chromium.org'),
  'ChromiumGitURL': ('https://chromium.googlesource.com',)
}

# This dict is used by Steps.gclient_common_spec. It contains standard
# configurations for commonly-needed gclient configurations. The format is:
#   { 'configname': lambda self: { ... gclient spec object ... } }
# self will be a Steps() instance.
GCLIENT_COMMON_SPECS = {
  'blink': lambda self: deep_set(
    GCLIENT_COMMON_SPECS['chromium'](self), [(
      'solutions.0.custom_deps',
      {'src/third_party/WebKit': self.ChromiumSvnURL('blink', 'trunk')}
    )]),

  'blink_bare': lambda self: {'solutions': [
    {
      'name': 'blink',
      'url': self.ChromiumSvnURL('blink', 'trunk'),
      'deps_file': '',
      'managed': True,
      'safesync_url': '',
    }]},

  'chromium': lambda self: {'solutions': [
    {
      'name' : 'src',
      'url' : self.ChromiumSvnURL('chrome', 'trunk', 'src'),
      'deps_file' : 'DEPS',
      'managed' : True,
      'custom_deps': {
        'src/third_party/WebKit/LayoutTests': None,
        'src/webkit/data/layout_tests/LayoutTests': None},
      'custom_vars': self.mirror_only({
        'googlecode_url': 'svn://svn-mirror.golo.chromium.org/%s',
        'nacl_trunk': 'http://src.chromium.org/native_client/trunk',
        'sourceforge_url': 'svn://svn-mirror.golo.chromium.org/%(repo)s',
        'webkit_trunk': 'svn://svn-mirror.golo.chromium.org/blink/trunk'}),
      'safesync_url': '',
    }]},

  'nacl': lambda self: {'solutions': [
    {
      "name":"native_client",
      "url": self.ChromiumSvnURL(
        'native_client', 'trunk', 'src', 'native_client'),
      "custom_deps":{},
      "custom_vars": self.mirror_only({
        "webkit_trunk":"svn://svn-mirror.golo.chromium.org/blink/trunk",
        "googlecode_url":"svn://svn-mirror.golo.chromium.org/%s",
        "sourceforge_url":"svn://svn-mirror.golo.chromium.org/%(repo)s"}),
    },
    {
      "name":"supplement.DEPS",
      "url": self.ChromiumSvnURL(
        'native_client', 'trunk', 'deps', 'supplement.DEPS'),
      "custom_deps":{},
      "custom_vars":{},
    }]},

  'tools_build': lambda self: {'solutions': [
    {
      'name': 'build',
      'url': self.ChromiumGitURL('chromium', 'tools', 'build.git'),
      'managed' : True,
      'deps_file' : '.DEPS.git',
    }]},
}


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


def _url_method(name):
  """Returns a shortcut static method which functions like os.path.join and uses
  a fixed first url component which is chosen from the urls defined in
  SOURCE_URLS based on |name|.
  """
  # note that we do the __name__ munging for each function separately because
  # staticmethod hides these attributes.
  bases = SOURCE_URLS[name]
  if len(bases) == 1:
    def url_func_inner_single(*pieces):
      """This function returns a url under '%s'."""
      return "/".join((bases[0],)+pieces)
    url_func_inner_single.__name__ = name
    url_func_inner_single.__doc__ = url_func_inner_single.__doc__ % bases
    url_func_inner_single = staticmethod(url_func_inner_single)
    return url_func_inner_single
  else:
    def url_func_inner_mirror(self, *pieces):
      """This function returns a url under '%s' or (mirror) '%s'.
      The mirror setting is extracted as self.use_mirror"""
      return "/".join((bases[self.use_mirror],)+pieces)
    url_func_inner_mirror.__name__ = name
    url_func_inner_mirror.__doc__ = url_func_inner_mirror.__doc__ % bases
    return url_func_inner_mirror


class Steps(object):
  """Provides methods to build steps that annotator.py understands."""

  ChromiumSvnURL = _url_method('ChromiumSvnURL')
  ChromiumGitURL = _url_method('ChromiumGitURL')

  def __init__(self, build_properties):
    self.build_properties = build_properties
    self.use_mirror = self.build_properties.get('use_mirror', True)

  def mirror_only(self, obj):
    """Returns obj if we're using mirrors. Otherwise returns the 'empty'
    version of obj."""
    return obj if self.use_mirror else obj.__class__()

  def gclient_common_spec(self, solution_name):
    """Returns a single gclient solution object (python dict) for common
    solutions."""
    return GCLIENT_COMMON_SPECS[solution_name](self)

  @staticmethod
  def step(name, cmd, add_properties=False, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py. Uses
    PropertyPlaceholder as a stand-in for build-properties and
    factory-properties so that annotated_run can fill them in after the recipe
    completes."""
    assert 'shell' not in kwargs
    assert isinstance(cmd, list)
    if add_properties:
      cmd += [PropertyPlaceholder]
    ret = kwargs
    ret.update({'name': name, 'cmd': cmd})
    return ret

  def apply_issue_step(self, root_pieces=None):
    return self.step('apply_issue', [
        depot_tools_path('apply_issue'),
        '-r', checkout_path(*(root_pieces or [])),
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
