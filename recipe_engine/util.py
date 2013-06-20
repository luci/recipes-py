# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module holds utilities which make writing recipes easier."""

import itertools
import json
import os
import tempfile

from common.chromium_utils import IsWindows, IsLinux, IsMac

from slave import gclient_configs
from slave import recipe_configs
from slave import recipe_configs_util


def path_method(name, base):
  """Returns a shortcut static method which functions like os.path.join with a
  fixed first component |base|.
  """
  def path_func_inner(*pieces, **kwargs):
    """This function returns a path to a file in '%s'.

    It supports the following kwargs:
      wrapper (bool): If true, the path should be considered to be a wrapper
                      script, and will gain the appropriate '.bat' extension
                      on windows.
    """
    WRAPPER_EXTENSION = ''
    if kwargs.get('wrapper') and IsWindows():
      WRAPPER_EXTENSION = '.bat'
    assert os.pardir not in pieces
    return os.path.join(base, *pieces) + WRAPPER_EXTENSION
  path_func_inner.__name__ = name
  path_func_inner.__doc__ = path_func_inner.__doc__ % base
  return path_func_inner


class _JsonPlaceholder(object):
  """Base class for json placeholders. Do not use directly."""
  def render(self, test_mode):
    """Return ([cmd items]*, [input files added]*, (output file added)?)"""
    raise NotImplementedError


class JsonOutputPlaceholder(_JsonPlaceholder):
  """JsonOutputPlaceholder is meant to be a singleton object which, when added
  to a step's cmd list, will be replaced by annotated_run with the command
  parameters --json-output /path/to/file during the evaluation of your recipe
  generator.

  This placeholder can be optionally added when you use the Steps.step()
  method in this module.

  After the termination of the step, this file is expected to contain a valid
  JSON document, which will be set as the json_output for that step in the
  step_history OrderedDict passed to your recipe generator.
  """
  def render(self, test_mode):
    items = ['--output-json']
    files = []
    output_file = None
    if test_mode:
      output_file = '/path/to/tmp/json'
      items.append(output_file)
    else:
      json_output_fd, output_file = tempfile.mkstemp()
      os.close(json_output_fd)
      items.append(output_file)
      files.append(output_file)
    return items, files, output_file
JsonOutputPlaceholder = JsonOutputPlaceholder()


class JsonInputPlaceholder(_JsonPlaceholder):
  """JsonInputPlaceholder is meant to be a non-singleton object which, when
  added to a step's cmd list, will be replaced by annotated_run with a
  /path/to/json file during the evaluation of your recipe generator.

  The file will have the json-serialized contents of the object passed to
  __init__, and is guaranteed to exist solely for the duration of the step.

  Multiple instances of thif placeholder can occur in a step's command, and
  each will be serialized to a different input file.
  """
  __slots__ = ['json_string']

  def __init__(self, data):
    self.json_string = json.dumps(data)
    super(JsonInputPlaceholder, self).__init__()

  def render(self, test_mode):
    if test_mode:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      return [self.json_string], [], None
    else:
      json_input_fd, json_input_name = tempfile.mkstemp()
      os.write(json_input_fd, self.json_string)
      os.close(json_input_fd)
      return [json_input_name], [json_input_name], None


class RecipeApi(object):
  """Provides methods to build steps that annotator.py understands."""

  def __init__(self, properties, mock_paths=None):
    self.properties = properties
    self.c = None
    self.auto_resolve_conflicts = False
    self.step_names = {}

    # These modules are intended to be passed through to recipes
    # pylint: disable=W0611
    self.json = json
    self.gclient_configs = gclient_configs
    self.recipe_configs = recipe_configs
    self.IsWindows = IsWindows()
    self.IsLinux = IsLinux()
    self.IsMac = IsMac()

    if mock_paths is None:
      slave_build_root = os.path.abspath(os.getcwd())
      # e.g. /b
      root = os.path.abspath(os.path.join(slave_build_root, os.pardir,
                                          os.pardir, os.pardir, os.pardir))
      # e.g. /b/build_internal
      build_internal_root = os.path.join(root, 'build_internal')
      # e.g. /b/build
      build_root = os.path.join(root, 'build')
      # e.g. /b/depot_tools
      depot_tools_root = os.path.join(root, 'depot_tools')
    else:
      slave_build_root = '[SLAVE_BUILD_ROOT]'
      root = '[ROOT]'
      build_internal_root = '[BUILD_INTERNAL_ROOT]'
      build_root = '[BUILD_ROOT]'
      depot_tools_root = '[DEPOT_TOOLS_ROOT]'

    # Recipes are expected to use each of these functions to generate paths for
    # use in annotator steps. See the documentation for path_method.
    self.depot_tools_path = path_method('depot_tools_path', depot_tools_root)
    self.build_internal_path = path_method('build_internal_path',
                                            build_internal_root)
    self.build_path = path_method('build_path', build_root)
    self.slave_build_path = path_method('slave_build_path', slave_build_root)

    """This function returns the equivalent of a path to a file in checkout
    root. It is not a 'real' path because it contains a string token which must
    be filled in by annotator_run.

    Example (assuming the checkout is a standard chromium checkout in 'src'):
      checkout_path('foobar')
        returns:
      "%(CheckoutRootPlaceholder)s/foobar"
        which, when run under annotator_run.py becomes:
      "/b/build/slave/win_rel/build/src/foobar"

    The actual checkout root is filled in by annotated_run after the recipe
    completes, and is dependent on the implementation of 'root()' in
    annotated_checkout for the checkout type that you've selected.

    NOTE: In order for this function to work, your recipe MUST have a step which
    sets CheckoutRoot in it's output json_data. This includes all the checkout
    methods in this Api.
    """  # pylint: disable=W0105
    self.checkout_path = path_method('checkout_path',
                                     '%(CheckoutRootPlaceholder)s')

    self._mock_paths = mock_paths


  def path_exists(self, path):
    mp = self._mock_paths
    return path in mp if mp is not None else os.path.exists(path)

  def set_common_configuration(self, config_name, **kwargs):
    """Sets a common configuration profile for this Steps instance.

    See recipe_configs.py for all the details.
    """
    config = self.recipe_configs.BaseConfig(**kwargs)
    getattr(self.recipe_configs, config_name)(config)
    self.c = config

  def property_json_args(self):
    """Helper function to generate build-properties and factory-properties
    arguments for LEGACY scripts.

    Since properties is the merge of build_properties and factory_properties,
    pass the merged dict as both arguments.

    It's vastly preferable to have your recipe only pass the bare minimum
    of arguments to steps. Passing property objects obscures the data that
    the script actually consumes from the property object.
    """
    return [
      '--factory-properties', json.dumps(self.properties),
      '--build-properties', json.dumps(self.properties)
    ]

  @staticmethod
  def json_input(jsonish_data):
    return JsonInputPlaceholder(jsonish_data)

  def step(self, name, cmd, add_json_output=False, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:
      name: The name of this step.
      cmd: A list of strings in the style of subprocess.Popen.
      add_json_output: Add JsonOutputPlaceholder iff True
      **kwargs: Additional entries to add to the annotator.py step dictionary.

    Returns:
      A step dictionary which is compatible with annotator.py.
    """
    assert 'shell' not in kwargs
    assert isinstance(cmd, list)
    cmd = list(cmd)  # Create a copy in order to not alter the input argument.
    if self.auto_resolve_conflicts:
      step_count = self.step_names.setdefault(name, 0) + 1
      self.step_names[name] = step_count
      if step_count > 1:
        name = "%s (%d)" % (name, step_count)
    if add_json_output:
      cmd += [JsonOutputPlaceholder]
    ret = kwargs
    ret.update({'name': name, 'cmd': cmd})
    return ret

  def apply_issue(self, *root_pieces):
    return self.step('apply_issue', [
        self.depot_tools_path('apply_issue'),
        '-r', self.checkout_path(*root_pieces),
        '-i', self.properties['issue'],
        '-p', self.properties['patchset'],
        '-s', self.properties['rietveld'],
        '-e', 'commit-bot@chromium.org'])

  def git(self, *args, **kwargs):
    name = 'git '+args[0]
    # Distinguish 'git config' commands by the variable they are setting.
    if args[0] == 'config' and not args[1].startswith('-'):
      name += ' ' + args[1]
    if 'cwd' not in kwargs:
      kwargs.setdefault('cwd', self.checkout_path())
    return self.step(name, ['git'] + list(args), **kwargs)

  def generator_script(self, path_to_script, *args):
    def step_generator(step_history, _failure):
      yield self.step(
        'gen step(%s)' % os.path.basename(path_to_script),
        [path_to_script,] + list(args),
        add_json_output=True,
        cwd=self.checkout_path())
      new_steps = step_history.last_step().json_data
      assert isinstance(new_steps, list)
      yield new_steps
    return step_generator

  def git_checkout(self, url, dir_path=None, branch='master', recursive=False,
                   keep_paths=None):
    """Returns an iterable of steps to perform a full git checkout.
    Args:
      url (string): url of remote repo to use as upstream
      dir_path (string): optional directory to clone into
      branch (string): branch to check out after fetching
      recursive (bool): whether to recursively fetch submodules or not
      keep_paths (iterable of strings): paths to ignore during git-clean;
          paths are gitignore-style patterns relative to checkout_path.
    """
    if not dir_path:
      dir_path = url.rsplit('/', 1)[-1]
      if dir_path.endswith('.git'):  # ex: https://host/foobar.git
        dir_path = dir_path[:-len('.git')]
      if not dir_path:  # ex: ssh://host:repo/foobar/.git
        dir_path = dir_path.rsplit('/', 1)[-1]
      dir_path = self.slave_build_path(dir_path)
    assert os.pardir not in dir_path
    recursive_args = ['--recurse-submodules'] if recursive else []
    clean_args = list(itertools.chain(
        *[('-e', path) for path in keep_paths or []]))
    return [
      self.step(
        'git setup', [
          self.build_path('scripts', 'slave', 'git_setup.py'),
          '--path', dir_path,
          '--url', url,
        ],
        static_json_data={
          'CheckoutRoot': dir_path,
          'CheckoutSCM': 'git',
          'CheckoutSpec': {
            'url': url,
            'recursive': recursive,
          },
        }),
      self.git('fetch', 'origin', *recursive_args),
      self.git('update-ref', 'refs/heads/'+branch, 'origin/'+branch),
      self.git('clean', '-f', '-d', '-x', *clean_args),
      self.git('checkout', '-f', branch),
      self.git('submodule', 'update', '--init', '--recursive', cwd=dir_path),
    ]

  def repo_checkout(self, url, root_path):
    """Returns an iterable of steps to perform a full repo checkout.
    Args:
      url (string): url of the manifest for repo to read
      root_path (string): the directory that will be pulled by repo that should
        be treated as the checkout_root.
    """
    init_step = None
    if not os.path.exists(self.slave_build_path('.repo', 'manifest.xml')):
      init_step = self.step('repo init', ['repo', 'init', '-u', url])
    sync_step = self.step(
        'repo sync', ['repo', 'sync'],
         static_json_data={
             'CheckoutRoot': root_path,
             'CheckoutSCM': 'repo',
             'CheckoutSpec': {
                 'manifest_url': url,
             },
         })
    steps = []
    if init_step:
      steps.append(init_step)
    steps.append(sync_step)
    return steps

  def gclient_checkout(self, common_repo_name_or_spec, git_mode=False,
                       spec_name=None, svn_revision=None):
    """Returns a step generator function for gclient checkouts."""
    # TODO(iannucci): Support revision property
    if isinstance(common_repo_name_or_spec, basestring):
      cfg = self.gclient_configs.BaseConfig(
        self.properties.get('use_mirror', True))
      getattr(self.gclient_configs, common_repo_name_or_spec)(cfg)
      spec = cfg.as_jsonish()
    elif isinstance(common_repo_name_or_spec, recipe_configs_util.ConfigBase):
      # TODO(iannucci): Make sure this conforms to gclient_config schema
      spec = common_repo_name_or_spec.as_jsonish()
    else:
      assert False
    spec_string = ''
    if not spec_name:
      step_name = lambda n: 'gclient ' + n
    else:
      step_name = lambda n: '[spec: %s] gclient %s' % (spec_name, n)
    for key in spec:
      # We should be using json.dumps here, but gclient directly execs the dict
      # that it receives as the argument to --spec, so we have to have True,
      # False, and None instead of JSON's true, false, and null.
      spec_string += '%s = %s\n' % (key, str(spec[key]))
    gclient = self.depot_tools_path('gclient', wrapper=True)

    gclient_sync_extra_args = []
    if svn_revision:
      gclient_sync_extra_args = ['--revision', svn_revision]

    if not git_mode:
      clean_step = self.gclient_revert(step_name)
      sync_step = self.step(step_name('sync'), [gclient, 'sync', '--nohooks'] +
                            gclient_sync_extra_args)
    else:
      # clean() isn't used because the gclient sync flags passed in checkout()
      # do much the same thing, and they're more correct than doing a separate
      # 'gclient revert' because it makes sure the other args are correct when
      # a repo was deleted and needs to be re-cloned (notably
      # --with_branch_heads), whereas 'revert' uses default args for clone
      # operations.
      #
      # TODO(mmoss): To be like current official builders, this step could just
      # delete the whole <slave_name>/build/ directory and start each build
      # from scratch. That might be the least bad solution, at least until we
      # have a reliable gclient method to produce a pristine working dir for
      # git-based builds (e.g. maybe some combination of 'git reset/clean -fx'
      # and removing the 'out' directory).
      clean_step = None
      sync_step = self.step(step_name('sync'), [
        gclient, 'sync', '--verbose', '--with_branch_heads', '--nohooks',
                     '--reset', '--delete_unversioned_trees', '--force'])
    steps = [
      self.step(
        step_name('setup'),
        [gclient, 'config', '--spec', spec_string],
        static_json_data={
          'CheckoutRoot': self.slave_build_path(spec['solutions'][0]['name']),
          'CheckoutSCM': 'gclient',
          'CheckoutSpec': spec
        }
      ),
    ]
    if clean_step:
      steps.append(clean_step)
    if sync_step:
      steps.append(sync_step)

    return steps

  def gclient_runhooks(self):
    return self.step(
      'gclient runhooks',
      [self.depot_tools_path('gclient', wrapper=True), 'runhooks'],
      env=self.c.gyp_env.as_jsonish(),
    )

  def gclient_revert(self, step_name_fn=lambda x: 'gclient '+x):
    return self.step(
      step_name_fn('revert'),
      ['python', self.build_path('scripts', 'slave', 'gclient_safe_revert.py'),
       '.', self.depot_tools_path('gclient', wrapper=True)],
    )

  def chromium_compile(self, targets=None):
    targets = targets or self.c.compile_py.default_targets.as_jsonish()
    assert isinstance(targets, (list, tuple))

    args = [
      'python', self.build_path('scripts', 'slave', 'compile.py'),
      '--target', self.c.BUILD_CONFIG,
      '--build-dir', self.checkout_path(self.c.build_dir)]
    if self.c.compile_py.build_tool:
      args += ['--build-tool', self.c.compile_py.build_tool]
    if self.c.compile_py.compiler:
      args += ['--compiler', self.c.compile_py.compiler]
    args.append('--')
    args.extend(targets)
    return self.step('compile', args)

  def runtests(self, test, args=None, xvfb=False, name=None, **kwargs):
    args = args or []
    assert isinstance(args, list)
    test_args = [test] + args

    python_arg = []
    t_name, ext = os.path.splitext(os.path.basename(test))
    if ext == '.py':
      python_arg = ['--run-python-script']

    return self.step(name or t_name, [
      'python', self.build_path('scripts', 'slave', 'runtest.py'),
      '--target', self.c.BUILD_CONFIG,
      '--build-dir', self.checkout_path(self.c.build_dir),
      ('--xvfb' if xvfb else '--no-xvfb')]
      + self.property_json_args()
      + python_arg
      + test_args,
      **kwargs
    )
