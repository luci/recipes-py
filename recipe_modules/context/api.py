# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""The context module provides APIs for manipulating a few pieces of 'ambient'
data that affect how steps are run:
  cwd - The current working directory.
  env - The environment variables.
  infra_step - Whether or not failures should be treated as infrastructure
    failures vs. normal failures.
  name_prefix - A prefix for all step names.
  nest_level - An indicator for the UI of how deeply to nest steps.

The values here are all scoped using Python's `with` statement; there's no
mechanism to make an open-ended adjustment to these values (i.e. there's no way
to change the cwd permanently for a recipe, except by surrounding the entire
recipe with a with statement). This is done to avoid the surprises that
typically arise with things like os.environ or os.chdir in a normal python
program.

Example:
  with api.context(cwd=api.path['start_dir'].join('subdir')):
    # this step is run inside of the subdir directory.
    api.step("cat subdir/foo", ['cat', './foo'])
"""


import collections

from contextlib import contextmanager

from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi


def check_type(name, var, expect):
  if not isinstance(var, expect):  # pragma: no cover
    raise TypeError('%s is not %s: %r (%s)' % (
      name, expect.__name__, var, type(var).__name__))


class ContextApi(RecipeApi):
  # TODO(iannucci): move implementation of these data directly into this class.
  def __init__(self, **kwargs):
    super(RecipeApi, self).__init__(**kwargs)

    self._cwd = [None]
    self._env = [{}]
    self._infra_step = [False]
    self._name_prefix = ['']
    # this could be a number, but it makes the logic easier to use a stack.
    self._nest_level = [0]

  @contextmanager
  def __call__(self, cwd=None, env=None, increment_nest_level=None,
               infra_steps=None, name_prefix=None):
    """Allows adjustment of multiple context values in a single call.

    Contextual data:
      * cwd (Path) - the current working directory to use for all steps.
        To 'reset' to the original cwd at the time recipes started, pass
        `api.path['start_dir']`.
      * infra_steps (bool) - if steps in this context should be considered
        infrastructure steps. On failure, these will raise InfraFailure
        exceptions instead of StepFailure exceptions.
      * increment_nest_level (True) - increment the nest level by 1 in this
        context. Typically you won't directly interact with this, but should
        use api.step.nest instead.
      * name_prefix (str) - A string to prepend to the names of all steps in
        this context. These compose with '.' characters if multiple name prefix
        contexts occur. See below for more info.
      * env (dict) - Environmental variable overrides. See below for more info.

    Name prefixes:

    Multiple invocations concatenate values with '.'.

    Example:
      with api.context(name_prefix='hello'):
        # has name 'hello.something'
        api.step('something', ['echo', 'something'])

        with api.context(name_prefix='world'):
          # has name 'hello.world.other'
          api.step('other', ['echo', 'other'])

    Environmental Variable Overrides:

    Env is a mapping of environment variable name to the value you want that
    environment variable to have. The value is a string, with a couple
    exceptions:
      * If value is None, this environment variable will be removed from the
        environment when the step runs.
      * String values will be %-formatted with the current value of the
        environment at the time the step runs. This means that you can have
        a value like:
          "/path/to/my/stuff:%(PATH)s"
        Which, at the time the step executes, will inject the current value of
        $PATH.

    TODO(iannucci): implement env_paths which allows for easier manipulation of
    `pathsep` environment variables like $PATH, $PYTHONPATH, etc.

    TODO(iannucci): combine nest_level and name_prefix

    Example:
      # suppose the OS's envar $OTHER is set to "yes"
      with api.context(env={'ENV_VAR': 'something:%(OTHER)s'}):
        # environment updates are additive.
        with api.context(env={'OTHER': 'cool:%(OTHER)s'}):
          # echos 'something:yes'
          # Note that the substitution always happens with the system
          # environment, not any of the computed environment here.
          api.step("check $ENV_VAR", ['bash', '-c', 'echo $ENV_VAR'])
          # echos 'cool:yes'
          api.step("check $OTHER", ['bash', '-c', 'echo $OTHER'])

        with api.context(env={'OTHER': None}):
          # echos ''
          api.step("check $OTHER", ['bash', '-c', 'echo $OTHER'])
    """
    to_pop = []

    if cwd is not None:
      check_type('cwd', cwd, Path)
      self._cwd.append(cwd)
      to_pop.append(self._cwd)

    if infra_steps is not None:
      check_type('infra_steps', infra_steps, bool)
      self._infra_step.append(infra_steps)
      to_pop.append(self._infra_step)

    if increment_nest_level is not None:
      check_type('increment_nest_level', increment_nest_level, bool)
      if not increment_nest_level:
        raise ValueError('increment_nest_level=False makes no sense')
      self._nest_level.append(self.nest_level+1)
      to_pop.append(self._nest_level)

    if name_prefix is not None:
      check_type('name_prefix', name_prefix, str)
      cur = self.name_prefix
      if cur:
        self._name_prefix.append('%s.%s' % (cur, name_prefix))
      else:
        self._name_prefix.append(name_prefix)
      to_pop.append(self._name_prefix)

    if env is not None and env != {}:
      check_type('env', env, dict)
      # we hit _env directly to avoid an extra copy.
      new = dict(self._env[-1])
      for k, v in env.iteritems():
        k = str(k)
        if v is not None:
          v = str(v)
          try:
            # This odd little piece of code does the following:
            #   * add a bogus dictionary format %(foo)s to v. This forces % into
            #     'dictionary lookup' mode
            #   * format the result with a defaultdict. This allows all
            #     `%(key)s` format lookups to succeed, but any sequential `%s`
            #     lookups to fail.
            # If the string contains any accidental sequential lookups, this
            # will raise an exception. If not, then this is a pluasible format
            # string.
            ('%(foo)s'+v) % collections.defaultdict(str)
          except Exception:
            raise ValueError(('Invalid %%-formatting parameter in envvar, '
                              'only %%(ENVVAR)s allowed: %r') % (v,))
        new[k] = v
      self._env.append(new)
      to_pop.append(self._env)

    try:
      yield
    finally:
      for p in to_pop:
        p.pop()

  @property
  def cwd(self):
    """Returns the current working directory that steps will run in.

    Returns (Path|None) - The current working directory. A value of None is
      equivalent to api.path['start_dir'], though only occurs if no cwd has been
      set (e.g. in the outermost context of RunSteps).
    """
    return self._cwd[-1]

  @property
  def env(self):
    """Returns modifications to the environment.

    By default this is empty; There's no facility to observe the program's
    startup environment. If you want to pass data to the recipe, it should be
    done with properties.

    Returns (dict) - The env-key -> value mapping of current environment
      modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._env[-1])

  @property
  def infra_step(self):
    """Returns the current value of the infra_step setting.

    Returns (bool) - True iff steps are currently considered infra steps.
    """
    return self._infra_step[-1]

  @property
  def name_prefix(self):
    """Gets the current step name prefix.

    Returns (str) - The string prefix that every step will have prepended to it.
    """
    return self._name_prefix[-1]

  @property
  def nest_level(self):
    """Returns the current 'nesting' level.

    Note: This api is low-level, and you should always prefer to use
    `api.step.nest`. This api is included for completeness and documentation
    purposes.

    Returns (int) - The current nesting level.
    """
    return self._nest_level[-1]
