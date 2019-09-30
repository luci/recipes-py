# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Defines classes which the `step` module uses to describe steps-to-run to the
RecipeEngine.

# TODO(iannucci): Simplify this.
"""

import attr

from .attr_util import attr_type, attr_dict_type, attr_seq_type, attr_value_is

from ..types import FrozenDict, freeze, thaw, ResourceCost
from ..util import InputPlaceholder, OutputPlaceholder, Placeholder, sentinel


@attr.s(frozen=True)
class EnvAffix(object):
  """Expresses a mapping of environment keys to a list of paths.

  This is used as StepConfig's "env_prefixes" and "env_suffixes" value.
  """
  mapping = attr.ib(factory=dict,
                    validator=attr_dict_type(str, str, value_seq=True))
  pathsep = attr.ib(default=None, validator=attr_type((str, type(None))))

  def __attrs_post_init__(self):
    object.__setattr__(self, 'mapping', freeze(self.mapping))


@attr.s(frozen=True)
class TriggerSpec(object):
  """TriggerSpec is the internal representation of a raw trigger step. You
  should use the standard 'step' recipe module, which will construct trigger
  specs via API.
  """
  # The name of the builder to trigger.
  builder_name = attr.ib(validator=attr_type(str))

  # The name of the trigger bucket.
  bucket = attr.ib(default='', validator=attr_type(str))

  # Key/value properties dictionary.
  properties = attr.ib(factory=dict, validator=attr_type((dict, FrozenDict)))

  # Optional list of BuildBot change dicts.
  buildbot_changes = attr.ib(default=(), validator=attr_seq_type(dict))

  # Optional list of tag strings.
  tags = attr.ib(default=(), validator=attr_seq_type(str))

  # If true and triggering fails asynchronously, fail the entire build.
  critical = attr.ib(default=True, validator=attr_type(bool))

  def _asdict(self):
    d = dict((k, v) for k, v in attr.asdict(self).iteritems() if v)
    if d['critical']:
      d.pop('critical')
    return d


def _file_placeholder(base_placeholder_type):
  """Returns a attr validator for StepConfig.stdin/stdout/stderr."""
  return [
    attr_type((str, base_placeholder_type, type(None))),
    attr_value_is(
        'backed by a file',
        lambda value: (
          value is None or isinstance(value, str) or
          value.backing_file is not Placeholder.backing_file
        )
    )
  ]


@attr.s
class StepConfig(object):
  """StepConfig is the representation of a raw step as the recipe_engine sees
  it.  You should use the standard 'step' recipe module, which will construct
  and pass this data to the engine for you, instead. The only reason why you
  would need to worry about this object is if you're modifying the step module
  itself.
  """
  # The name of the step to run within the current namespace.
  #
  # This will be deduplicated by the recipe engine.
  name = attr.ib(validator=attr_type(basestring))

  # List of args of the command to run. Acceptable types: Placeholder or any
  # str()'able type.
  cmd = attr.ib(
      default=(),
      converter=(lambda value: [
        itm if isinstance(itm, Placeholder) else str(itm)
        for itm in value
      ]),
      validator=attr_seq_type((str, Placeholder)))

  # Absolute path to working directory for the command.
  cwd = attr.ib(
      default=None,
      validator=attr_type((str, type(None))))

  # Step resource cost.
  cost = attr.ib(default=None, validator=attr_type(ResourceCost, type(None)))

  # Overrides for environment variables
  #
  # Each value is % formatted with the entire existing os.environ. A value of
  # `None` will remove that envvar from the environ. e.g.
  #
  #   {
  #      "envvar": "%(envvar)s-extra",
  #      "delete_this": None,
  #      "static_value": "something",
  #   }
  #
  # The "env_prefixes" parameter contain values that transform an environment
  # variable into a "pathsep"-delimited sequence of items:
  #   - If an environment variable is also specified for this key, it will be
  #     appended as the last element: <prefix0>:...:<prefixN>:ENV
  #   - If no environment variable is specified, the current environment's value
  #     will be appended, unless it's empty: <prefix0>:...:<prefixN>[:ENV]?
  #   - If an environment variable with a value of None (delete) is specified,
  #     nothing will be appeneded: <prefix0>:...:<prefixN>
  # "env_suffixes" is identical, except that it appends instead of prepends to
  # the envvar.
  #
  # NOTE: Always prefer env_prefixes and env_suffixes to manually substituting
  # variables with %(envvar)s.
  env = attr.ib(factory=dict, validator=attr_dict_type(str, (str, type(None))))
  env_prefixes = attr.ib(factory=EnvAffix, validator=attr_type(EnvAffix))
  env_suffixes = attr.ib(factory=EnvAffix, validator=attr_type(EnvAffix))

  # If True, lets the step emit its own @@@annotations@@@.
  #
  # TODO(iannucci): Move this into an annotee wrapper command in the `step`
  # module.
  #
  # NOTE: Enabling this can cause some buggy behavior. Use
  # step_result.presentation instead. If you have questions, please contact
  # infra-dev@chromium.org.
  allow_subannotations = attr.ib(default=False, validator=attr_type(bool))

  # The time, in seconds, that this step is allowed to run for before timing
  # out.
  timeout = attr.ib(
      default=None,
      validator=attr_type((int, float, long, type(None))))

  # Set of return codes allowed. If the step process returns something not on
  # this list, it will raise a StepFailure (or InfraFailure if infra_step is
  # True).
  #
  # Alternatively, the sentinel StepConfig.ALL_OK can be used to allow any
  # return code.
  ok_ret = attr.ib(default=(0,))
  @ok_ret.validator
  def _ok_ret_validator(self, attrib, value):
    if value is self.ALL_OK:
      return
    attr_seq_type((int, long))(self, attrib, value)

  # If True and the step returns an unacceptable return code (see `ok_ret`),
  # this will raise InfraFailure instead of StepFailure.
  infra_step = attr.ib(default=False, validator=attr_type(bool))

  # Standard handle redirection.
  # If None, stdin is closed and stdout/stderr are routed to the UI.
  # These placeholders require a non-default implementation of `backing_file`.
  stdin = attr.ib(default=None, validator=_file_placeholder(InputPlaceholder))
  stdout = attr.ib(default=None, validator=_file_placeholder(OutputPlaceholder))
  stderr = attr.ib(default=None, validator=_file_placeholder(OutputPlaceholder))

  # A function returning recipe_test_api.StepTestData.
  #
  # A factory which returns a StepTestData object that will be used as the
  # default test data for this step. The recipe author can override/augment this
  # object in the GenTests function.
  step_test_data = attr.ib(
      default=None,
      validator=attr_value_is(
          'None or callable',
          lambda value: value is None or callable(value)))

  # DEPRECATED: Do not use this.
  trigger_specs = attr.ib(default=(), validator=attr_seq_type(TriggerSpec))

  def __attrs_post_init__(self):
    object.__setattr__(self, 'cmd', tuple(self.cmd))
    object.__setattr__(self, 'trigger_specs', tuple(self.trigger_specs))

    # if cmd is empty, then remove all values except for the few that actually
    # apply with a null command.
    if not self.cmd:
      _keep_fields = ('name', 'cmd', 'trigger_specs')
      for attrib in attr.fields(self.__class__):
        if attrib.name in _keep_fields:
          continue
        # cribbed from attr/_make.py; the goal is to compute the attribute's
        # default value.
        if isinstance(attrib.default, attr.Factory):
          if attrib.default.takes_self:
            val = attrib.default.factory(self)
          else:
            val = attrib.default.factory()
        else:
          val = attrib.default
        if attrib.converter:
          val = attrib.converter(val)
        object.__setattr__(self, attrib.name, val)
      object.__setattr__(self, 'cost', ResourceCost.zero())
      return

    if self.ok_ret is not self.ALL_OK:
      object.__setattr__(self, 'ok_ret', frozenset(self.ok_ret))
    object.__setattr__(self, 'env', freeze(self.env))

    # Ensure that output placeholders don't have ambiguously overlapping names.
    placeholders = set()
    collisions = set()
    ns_str = None
    for itm in self.cmd:
      if isinstance(itm, OutputPlaceholder):
        key = itm.namespaces, itm.name
        if key in placeholders:
          ns_str = '.'.join(itm.namespaces)
          if itm.name is None:
            collisions.add("{} unnamed".format(ns_str))
          else:
            collisions.add("{} named {!r}".format(ns_str, itm.name))
        else:
          placeholders.add(key)

    if collisions:
      raise ValueError(
          'Found conflicting Placeholders: {!r}. Please give these placeholders'
          ' unique "name"s and access them like `step_result.{}s[name]`.'
          .format(list(collisions), ns_str))


  # Used with to indicate that all retcodes values are acceptable.
  ALL_OK = sentinel('ALL_OK')

  _RENDER_WHITELIST=frozenset((
    'cmd',
  ))

  _RENDER_BLACKLIST=frozenset((
    'env_prefixes',
    'env_suffixes',
    'ok_ret',
    'step_test_data',
    'trigger_specs',
  ))

  def _asdict(self):
    ret = thaw(attr.asdict(self, filter=(lambda attr, val: (
      (val and val != attr.default or (attr.name in self._RENDER_WHITELIST)) and
      attr.name not in self._RENDER_BLACKLIST
    ))))
    if self.env_prefixes.mapping:
      ret['env_prefixes'] = dict(self.env_prefixes.mapping)
    if self.env_suffixes.mapping:
      ret['env_suffixes'] = dict(self.env_suffixes.mapping)
    if self.trigger_specs:
      ret['trigger_specs'] = [ts._asdict() for ts in self.trigger_specs]
    return ret
