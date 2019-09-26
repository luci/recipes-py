# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""The context module provides APIs for manipulating a few pieces of 'ambient'
data that affect how steps are run.

The pieces of information which can be modified are:
  * cwd - The current working directory.
  * env - The environment variables.
  * infra_step - Whether or not failures should be treated as infrastructure
    failures vs. normal failures.

The values here are all scoped using Python's `with` statement; there's no
mechanism to make an open-ended adjustment to these values (i.e. there's no way
to change the cwd permanently for a recipe, except by surrounding the entire
recipe with a with statement). This is done to avoid the surprises that
typically arise with things like os.environ or os.chdir in a normal python
program.

Example:
```python
with api.context(cwd=api.path['start_dir'].join('subdir')):
  # this step is run inside of the subdir directory.
  api.step("cat subdir/foo", ['cat', './foo'])
```
"""


import collections

from contextlib import contextmanager

from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi


def check_type(name, var, expect):
  if not isinstance(var, expect):  # pragma: no cover
    raise TypeError('%s is not %s: %r (%s)' % (
      name, expect.__name__, var, type(var).__name__))


class ContextApi(RecipeApi):

  # TODO(iannucci): move implementation of these data directly into this class.
  def __init__(self, **kwargs):
    super(ContextApi, self).__init__(**kwargs)

    self._cwd = [None]
    self._env_prefixes = [{}]
    self._env_suffixes = [{}]
    self._env = [{}]
    self._infra_step = [False]

  @contextmanager
  def __call__(self, cwd=None, env_prefixes=None, env_suffixes=None, env=None,
               infra_steps=None):
    """Allows adjustment of multiple context values in a single call.

    Args:
      * cwd (Path) - the current working directory to use for all steps.
        To 'reset' to the original cwd at the time recipes started, pass
        `api.path['start_dir']`.
      * env_prefixes (dict) - Environmental variable prefix augmentations. See
          below for more info.
      * env_suffixes (dict) - Environmental variable suffix augmentations. See
          below for more info.
      * env (dict) - Environmental variable overrides. See below for more info.
      * infra_steps (bool) - if steps in this context should be considered
        infrastructure steps. On failure, these will raise InfraFailure
        exceptions instead of StepFailure exceptions.

    Environmental Variable Overrides:

    Env is a mapping of environment variable name to the value you want that
    environment variable to have. The value is one of:
      * None, indicating that the environment variable should be removed from
        the environment when the step runs.
      * A string value. Note that string values will be %-formatted with the
        current value of the environment at the time the step runs. This means
        that you can have a value like:
            "/path/to/my/stuff:%(PATH)s"
        Which, at the time the step executes, will inject the current value of
        $PATH.

    "env_prefix" and "env_suffix" are a list of Path or strings that get
    prefixed (or suffixed) to their respective environment variables, delimited
    with the system's path separator. This can be used to add entries to
    environment variables such as "PATH" and "PYTHONPATH". If prefixes are
    specified and a value is also defined in "env", the value will be installed
    as the last path component if it is not empty.

    Look at the examples in "examples/" for examples of context module usage.
    """
    def _push(st, val):
      st.append(val)
      to_pop.append(st)

    def add_to_context(kwarg_name, kwarg_val, current, adder_func):
      if kwarg_val is not None and len(kwarg_val) > 0:
        check_type(kwarg_name, kwarg_val, dict)
        new = dict(current[-1])
        for k, v in kwarg_val.iteritems():
          adder_func(k, v, new)
        _push(current, new)

    def check_accidental_sequential_lookups(v):
      try:
        # This odd little piece of code does the following:
        #   * add a bogus dictionary format %(foo)s to v. This forces %
        #     into 'dictionary lookup' mode
        #   * format the result with a defaultdict. This allows all
        #     `%(key)s` format lookups to succeed, but any sequential `%s`
        #     lookups to fail.
        # If the string contains any accidental sequential lookups, this
        # will raise an exception. If not, then this is a plausible format
        # string.
        ('%(foo)s' + v) % collections.defaultdict(str)
      except Exception:
        raise ValueError(('Invalid %%-formatting parameter in envvar, '
                          'only %%(ENVVAR)s allowed: %r') % (v,))

    def _as_env_prefixes(k, v, new):
      if v:
        new[k] = tuple(v) + new.get(k, ())

    def _as_env_suffixes(k, v, new):
      if v:
        new[k] = new.get(k, ()) + tuple(v)

    def _as_env(k, v, new):
      if v is not None:
        v = str(v)
        check_accidental_sequential_lookups(v)
      new[k] =  v

    to_pop = []

    if cwd is not None:
      check_type('cwd', cwd, Path)
      _push(self._cwd, cwd)

    if infra_steps is not None:
      check_type('infra_steps', infra_steps, bool)
      _push(self._infra_step, infra_steps)

    add_to_context(
      'env_prefixes', env_prefixes, self._env_prefixes, _as_env_prefixes)

    add_to_context(
      'env_suffixes', env_suffixes, self._env_suffixes, _as_env_suffixes)

    add_to_context(
      'env', env, self._env, _as_env)

    try:
      yield
    finally:
      for p in to_pop:
        p.pop()




  @property
  def cwd(self):
    """Returns the current working directory that steps will run in.

    **Returns (Path|None)** - The current working directory. A value of None is
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

    **Returns (dict)** - The env-key -> value mapping of current environment
      modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._env[-1])

  @property
  def env_prefixes(self):
    """Returns Path prefix modifications to the environment.

    This will return a mapping of environment key to Path tuple for Path
    prefixes registered with the environment.

    **Returns (dict)** - The env-key -> value(Path) mapping of current
    environment prefix modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._env_prefixes[-1])

  @property
  def env_suffixes(self):
    """Returns Path suffix modifications to the environment.

    This will return a mapping of environment key to Path tuple for Path
    suffixes registered with the environment.

    **Returns (dict)** - The env-key -> value(Path) mapping of current
    environment suffix modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._env_suffixes[-1])

  @property
  def infra_step(self):
    """Returns the current value of the infra_step setting.

    **Returns (bool)** - True iff steps are currently considered infra steps.
    """
    return self._infra_step[-1]
