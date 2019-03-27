# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Defines classes which the `step` module uses to describe steps-to-run to the
RecipeEngine.

# TODO(iannucci): Simplify this.
"""

import pprint

from collections import namedtuple

from ..util import Placeholder, sentinel


class EnvAffix(namedtuple('_EnvAffix', (
    'mapping', 'pathsep'))):
  """Expresses a mapping of environment keys to a list of paths.

  This is used as StepConfig's "env_prefixes" and "env_suffixes" value.
  """

  @classmethod
  def empty(cls):
    return cls(mapping={}, pathsep=None)

  def render_step_value(self):
    rendered = {k: (self.pathsep or ':').join(str(x) for x in v)
                for k, v in self.mapping.iteritems()}
    return pprint.pformat(rendered, width=1024)


class StepConfig(namedtuple('_StepConfig', (
    'name_tokens', 'cmd', 'cwd', 'env', 'env_prefixes', 'env_suffixes',
    'allow_subannotations', 'trigger_specs', 'timeout', 'infra_step',
    'stdout', 'stderr', 'stdin', 'ok_ret', 'step_test_data'))):

  """
  StepConfig is the representation of a raw step as the recipe_engine sees it.
  You should use the standard 'step' recipe module, which will construct and
  pass this data to the engine for you, instead. The only reason why you would
  need to worry about this object is if you're modifying the step module
  itself.

  Fields:
    name_tokens (List[str]): The list of name pieces for this step.
    cmd: command to run. Acceptable types: str, Path, Placeholder, or None.
    cwd (str or None): absolute path to working directory for the command
    env (dict): overrides for environment variables, described above.
    env_prefixes (dict): environment prefix variables, mapping environment
      variable names to EnvAffix values.
    env_suffixes (dict): environment suffix variables, mapping environment
      variable names to EnvAffix values.
    allow_subannotations (bool): if True, lets the step emit its own
        annotations. NOTE: Enabling this can cause some buggy behavior. Please
        strongly consider using step_result.presentation instead. If you have
        questions, please contact infra-dev@chromium.org.
    trigger_specs: a list of trigger specifications, see also _trigger_builds.
    timeout: if not None, a datetime.timedelta for the step timeout.
    infra_step: if True, this is an infrastructure step. Failures will raise
        InfraFailure instead of StepFailure.
    stdout: Placeholder to put step stdout into. If used, stdout won't appear
        in annotator's stdout (and |allow_subannotations| is ignored).
    stderr: Placeholder to put step stderr into. If used, stderr won't appear
        in annotator's stderr.
    stdin: Placeholder to read step stdin from.
    ok_ret (iter, ALL_OK): set of return codes allowed. If the step process
        returns something not on this list, it will raise a StepFailure (or
        InfraFailure if infra_step is True). If omitted, {0} will be used.
        Alternatively, the sentinel StepConfig.ALL_OK can be used to allow any
        return code.
    step_test_data (func -> recipe_test_api.StepTestData): A factory which
        returns a StepTestData object that will be used as the default test
        data for this step. The recipe author can override/augment this object
        in the GenTests function.

  The optional "env" parameter provides optional overrides for environment
  variables. Each value is % formatted with the entire existing os.environ. A
  value of `None` will remove that envvar from the environ. e.g.

    {
        "envvar": "%(envvar)s;%(envvar2)s;extra",
        "delete_this": None,
        "static_value": "something",
    }

  The optional "env_prefixes" (and similarly "env_suffixes") parameters
  contains values that, if specified, will transform an environment variable
  into a "pathsep"-delimited sequence of items:
    - If an environment variable is also specified for this key, it will be
      appended as the last element: <prefix0>:...:<prefixN>:ENV
    - If no environment variable is specified, the current environment's value
      will be appended, unless it's empty: <prefix0>:...:<prefixN>[:ENV]?
    - If an environment variable with a value of None (delete) is specified,
      nothing will be appeneded: <prefix0>:...:<prefixN>

  There is currently no way to remove prefix paths; once they're there,
  they're there for good. If you think you need to remove paths from the
  prefix lists, please talk to infra-dev@chromium.org.
  """
  # Used with to indicate that all retcodes values are acceptable.
  ALL_OK = sentinel('ALL_OK')

  _RENDER_WHITELIST=frozenset((
    'cmd',
  ))

  _RENDER_BLACKLIST=frozenset((
    'name_tokens',
    'ok_ret',
    'step_test_data',
  ))

  @property
  def name(self):
    """Returns a '.' separated string version of name_tokens for backwards
    compatibility with old recipe engine code."""
    # TODO(iannucci): Remove this method or make it use '|' separators
    # instead.
    return '.'.join(self.name_tokens)

  def __new__(cls, **kwargs):
    for field in cls._fields:
      kwargs.setdefault(field, None)
    sc = super(StepConfig, cls).__new__(cls, **kwargs)

    return sc._replace(
        cmd=[(x if isinstance(x, Placeholder) else str(x))
             for x in (sc.cmd or ())],
        cwd=(str(sc.cwd) if sc.cwd else (None)),
        env=sc.env or {},
        env_prefixes=sc.env_prefixes or EnvAffix.empty(),
        env_suffixes=sc.env_suffixes or EnvAffix.empty(),
        allow_subannotations=bool(sc.allow_subannotations),
        trigger_specs=sc.trigger_specs or (),
        infra_step=bool(sc.infra_step),
        ok_ret=(sc.ok_ret if sc.ok_ret is StepConfig.ALL_OK
                else frozenset(sc.ok_ret or (0,))),
    )

  def render_to_dict(self):
    sc = self._replace(
        env_prefixes={k: list(str(e) for e in v)
                      for k, v in self.env_prefixes.mapping.iteritems()},
        env_suffixes={k: list(str(e) for e in v)
                      for k, v in self.env_suffixes.mapping.iteritems()},
        trigger_specs=[trig._render_to_dict()
                       for trig in (self.trigger_specs or ())],
    )
    ret = dict((k, v) for k, v in sc._asdict().iteritems()
                if (v or k in sc._RENDER_WHITELIST)
                and k not in sc._RENDER_BLACKLIST)
    ret['name'] = self.name
    return ret


class TriggerSpec(namedtuple('_TriggerSpec', (
    'bucket', 'builder_name', 'properties', 'buildbot_changes', 'tags',
    'critical'))):

  """
  TriggerSpec is the internal representation of a raw trigger step. You should
  use the standard 'step' recipe module, which will construct trigger specs
  via API.

  Fields:
    builder_name (str): The name of the builder to trigger.
    bucket (str or None): The name of the trigger bucket.
    properties (dict or None): Key/value properties dictionary.
    buildbot_changes (list or None): Optional list of BuildBot change dicts.
    tags (list or None): Optional list of tag strings.
    critical (bool or None): If true and triggering fails asynchronously, fail
        the entire build. If None, the step defaults to being True.
  """

  def __new__(cls, **kwargs):
    for field in cls._fields:
      kwargs.setdefault(field, None)
    trig = super(TriggerSpec, cls).__new__(cls, **kwargs)
    return trig._replace(
        critical=bool(trig.critical),
    )

  def _render_to_dict(self):
    d = dict((k, v) for k, v in self._asdict().iteritems() if v)
    if d['critical']:
      d.pop('critical')
    return d
