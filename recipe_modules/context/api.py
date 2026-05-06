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
with api.context(cwd=api.path.start_dir / 'subdir'):
  # this step is run inside of the subdir directory.
  api.step("cat subdir/foo", ['cat', './foo'])
```
"""

from __future__ import annotations

import collections
from collections.abc import Mapping
import contextlib
import copy
from typing import Sequence

from google.protobuf import json_format as jsonpb

from recipe_engine import config_types, recipe_api
from recipe_engine.config_types import Path
from recipe_engine.engine_types import PerGreenletState, freeze

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2

def check_type(name, var, expect):
  if not isinstance(var, expect):  # pragma: no cover
    raise TypeError('%s is not %s: %r (%s)' % (
      name, expect.__name__, var, type(var).__name__))


class State(PerGreenletState):
  # Default to immutable types to prevent these from accidentally becoming
  # global variables.
  cwd: config_types.Path | None = None
  env_prefixes: dict[str, Sequence[str]] = freeze({})
  env_suffixes: dict[str, Sequence[str]] = freeze({})
  env: dict[str, str] = freeze({})
  infra_steps: bool = False
  luci_context = freeze({})

  def _get_setter_on_spawn(self):
    old_cwd = self.cwd
    old_env_prefixes = self.env_prefixes
    old_env_suffixes = self.env_suffixes
    old_env = self.env
    old_infra_steps = self.infra_steps
    old_luci_context = self.luci_context

    def _inner():
      self.cwd = old_cwd
      self.env_prefixes = old_env_prefixes
      self.env_suffixes = old_env_suffixes
      self.env = old_env
      self.infra_steps = old_infra_steps
      self.luci_context = old_luci_context

    return _inner


class ContextApi(recipe_api.RecipeApi):
  _lucictx_client = recipe_api.RequireClient('lucictx')

  # TODO(iannucci): move implementation of these data directly into this class.
  def __init__(self, **kwargs):
    super().__init__(**kwargs)

    self._state = State()
    self._test_counter: int = 0

  def initialize(self) -> None:
    ctx = self._lucictx_client.initial_context
    if ctx:
      # Add other LUCI_CONTEXT sections in the following dict to support
      # modification through this module.
      init_sections = {
        'deadline': sections_pb2.Deadline,
        'luciexe': sections_pb2.LUCIExe,
        'realm': sections_pb2.Realm,
        'resultdb': sections_pb2.ResultDB,
      }

      # reset luci_context so that when we write into it without it becoming
      # a global variable.
      self._state.luci_context = {}
      for section_key, section_msg_class in init_sections.items():
        if section_key in ctx:
          self._state.luci_context[section_key] = (
              jsonpb.ParseDict(ctx[section_key],
                               section_msg_class(),
                               ignore_unknown_fields=True))

  @contextlib.contextmanager
  def __call__(
      self,
      cwd: config_types.Path | None = None,
      env_prefixes: Mapping[str, Sequence[str]] | None = None,
      env_suffixes: Mapping[str, Sequence[str]] | None = None,
      env: Mapping[str, str] | None = None,
      infra_steps: bool | None = None,
      luciexe: sections_pb2.LUCIExe | None = None,
      realm: str = None,
      deadline: sections_pb2.Deadline | None = None,
  ):
    """Allows adjustment of multiple context values in a single call.

    Args:
      * cwd - the current working directory to use for all steps.
        To 'reset' to the original cwd at the time recipes started, pass
        `api.path.start_dir`.
      * env_prefixes - Environmental variable prefix augmentations. See below
        for more info.
      * env_suffixes - Environmental variable suffix augmentations. See below
        for more info.
      * env - Environmental variable overrides. See below for more info.
      * infra_steps - if steps in this context should be considered
        infrastructure steps. On failure, these will raise InfraFailure
        exceptions instead of StepFailure exceptions.
      * luciexe - The override value for 'luciexe' section in LUCI_CONTEXT.
        This is currently used to modify the `cache_dir` for all launched LUCI
        Executable (via `api.step.sub_build(...)`).
      * realm - allows changing the current LUCI realm. It is used when
        creating new LUCI resources (e.g. spawning new Swarming tasks). Pass an
        empty string to disassociate the context from a realm, emulating an
        environment prior to LUCI realms. This is useful during the
        transitional period.
      * deadline - Deadline information to set; See LUCI_CONTEXT documentation
        for how this section works. Automatically adjusted by steps with
        `timeout` set.

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
    # Mapping of state member to value to assign on exit of this function.
    deferred_assignments = {}

    def _push(state_member: str, new: Any):
      deferred_assignments[state_member] = _get_current(state_member)
      setattr(self._state, state_member, new)

    def _get_current(state_member: str):
      return getattr(self._state, state_member)

    def _add_to_context(state_member: str, to_add, adder_func):
      if to_add is not None and to_add:
        check_type(state_member, to_add, dict)
        new = dict(_get_current(state_member))
        for key, val in to_add.items():
          adder_func(key, val, new)
        _push(state_member, new)

    def _as_env_prefixes(key, val, new):
      if val:
        new[key] = tuple(val) + new.get(key, ())

    def _as_env_suffixes(key, val, new):
      if val:
        new[key] = new.get(key, ()) + tuple(val)

    def _as_env(key, val, new):
      if val is not None:
        val = str(val)
        try:
          # This odd little piece of code does the following:
          #   * add a bogus dictionary format %(foo)s to val. This forces %
          #     into 'dictionary lookup' mode
          #   * format the result with a defaultdict. This allows all
          #     `%(key)s` format lookups to succeed, but any sequential `%s`
          #     lookups to fail.
          # If the string contains any accidental sequential lookups, this
          # will raise an exception. If not, then this is a plausible format
          # string.
          ('%(foo)s' + val) % collections.defaultdict(str)
        except Exception:
          raise ValueError(('Invalid %%-formatting parameter in envvar, '
                            'only %%(ENVVAR)s allowed: %r') % (val,))
      new[key] = val

    def _override(key, val, new):
      new[key] = val

    try:
      if cwd is not None:
        check_type('cwd', cwd, Path)
        _push('cwd', cwd)

      if infra_steps is not None:
        check_type('infra_steps', infra_steps, bool)
        _push('infra_steps', infra_steps)

      section_pb_values = {}
      if luciexe:
        check_type('luciexe', luciexe, sections_pb2.LUCIExe)
        section_pb_values['luciexe'] = copy.deepcopy(luciexe)
      if realm is not None:
        section_pb_values['realm'] = (
            sections_pb2.Realm(name=realm) if realm else None)
      if deadline is not None:
        check_type('deadline', deadline, sections_pb2.Deadline)
        cur_deadline = self.deadline
        if (cur_deadline.soft_deadline and
            cur_deadline.soft_deadline < deadline.soft_deadline):
          raise ValueError(
              "Deadline.soft_deadline being increased: %f->%f" % (
                cur_deadline.soft_deadline, deadline.soft_deadline))
        if cur_deadline.grace_period < deadline.grace_period:
          raise ValueError(
              "Deadline.grace_period being increased: %f->%f" % (
                cur_deadline.grace_period, deadline.grace_period))
        section_pb_values['deadline'] = copy.deepcopy(deadline)
      if section_pb_values:
        _add_to_context('luci_context', section_pb_values, _override)

      _add_to_context('env_prefixes', env_prefixes, _as_env_prefixes)

      _add_to_context('env_suffixes', env_suffixes, _as_env_suffixes)

      _add_to_context('env', env, _as_env)

      yield
    finally:
      for state_member, val in deferred_assignments.items():
        setattr(self._state, state_member, val)

  @property
  def cwd(self) -> config_types.Path | None:
    """Returns the current working directory that steps will run in.

    **Returns (Path|None)** - The current working directory. A value of None is
    equivalent to api.path.start_dir, though only occurs if no cwd has been
    set (e.g. in the outermost context of RunSteps).
    """
    return self._state.cwd

  @property
  def env(self) -> dict[str, str]:
    """Returns modifications to the environment.

    By default this is empty. If you want to observe the program's startup
    environment, see `ENV_PROPERTIES` in
    https://chromium.googlesource.com/infra/luci/recipes-py/+/refs/heads/main/doc/user_guide.md#properties-and-env_properties

    **Returns (dict)** - The env-key -> value mapping of current environment
      modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._state.env)

  @property
  def env_prefixes(self) -> dict[str, tuple[str]]:
    """Returns Path prefix modifications to the environment.

    This will return a mapping of environment key to Path tuple for Path
    prefixes registered with the environment.

    **Returns (dict)** - The env-key -> value(Path) mapping of current
    environment prefix modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._state.env_prefixes)

  @property
  def env_suffixes(self) -> dict[str, tuple[str]]:
    """Returns Path suffix modifications to the environment.

    This will return a mapping of environment key to Path tuple for Path
    suffixes registered with the environment.

    **Returns (dict)** - The env-key -> value(Path) mapping of current
    environment suffix modifications.
    """
    # TODO(iannucci): store env in an immutable way to avoid excessive copies.
    # TODO(iannucci): handle case-insensitive keys on windows
    return dict(self._state.env_suffixes)

  @property
  def infra_step(self) -> bool:
    """Returns the current value of the infra_step setting.

    **Returns (bool)** - True iff steps are currently considered infra steps.
    """
    return self._state.infra_steps

  @property
  def luci_context(self):
    """Returns the currently tracked LUCI_CONTEXT sections as a dict of proto
    messages.

    Only contains `luciexe`, `realm`, 'resultdb' and `deadline`.
    """
    ret = {}
    for section, msg in self._state.luci_context.items():
      ret[section] = copy.deepcopy(msg)
    return ret

  @property
  def luciexe(self) -> sections_pb2.LUCIExe | None:
    """Returns the current value (sections_pb2.LUCIExe) of luciexe section in
    the current LUCI_CONTEXT. Returns None if luciexe is not defined."""
    ret = None
    if 'luciexe' in self._state.luci_context:
      ret = sections_pb2.LUCIExe()
      ret.CopyFrom(self._state.luci_context['luciexe'])
    return ret

  @property
  def realm(self) -> str | None:
    """Returns the LUCI realm of the current context.

    May return None if the task is not running in the realm-aware mode. This is
    a transitional period. Eventually all tasks will be associated with realms.
    """
    sec = self._state.luci_context.get('realm')
    return sec.name if sec and sec.name else None

  @property
  def deadline(self) -> sections_pb2.Deadline:
    """Returns the current value (sections_pb2.Deadline) of deadline section in
    the current LUCI_CONTEXT. Returns `{grace_period: 30}` if deadline is not
    defined, per LUCI_CONTEXT spec."""
    if 'deadline' in self._state.luci_context:
      ret = sections_pb2.Deadline()
      ret.CopyFrom(self._state.luci_context['deadline'])
      return ret
    return sections_pb2.Deadline(grace_period=30)

  @property
  def resultdb_invocation_name(self) -> str:
    """Returns the ResultDB invocation name of the current context.

    Returns None if resultdb is not defined.
    """
    resultdb = self._state.luci_context.get('resultdb')
    return (resultdb.current_invocation.name if
            resultdb and resultdb.current_invocation else '')
