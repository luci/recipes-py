# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe Configuration Meta DSL.

This module contains, essentially, a DSL for writing composable configurations.
You start by defining a schema which describes how your configuration blobs will
be structured, and what data they can contain. For example:

  FakeSchema = lambda main_val=True, mode='Happy': ConfigGroup(
    config_group = ConfigGroup(
      item_a = SimpleConfig(int),
      item_b = DictConfig(),
    ),
    extra_setting = SetConfig(str),

    MAIN_DETERMINANT = StaticConfig(main_val),
    CONFIG_MODE = StaticConfig(mode),
  )

In short, a 'schema' is a callable which can take zero arguments (it can contain
default arguments as well, for setting defaults, tweaking the schema, etc.), and
returning a ConfigGroup.

Every type used in the schema derives from ConfigBase. It has the general
characteristics that it's a fixed-type container. It tends to impersonate the
data type that it stores (so you can manipulate the config objects like normal
python data), but also provides type checking and type conversion assistence
(so you can easily render your configurations to JSON).

Once you have your schema, you define some testing data:
  TEST_MAP = {
    'MAIN_DETERMINANT': (True, False),
    'CONFIG_MODE': ('Happy', 'Sad'),
  }
  TEST_NAME_FORMAT = '%(MAIN_DETERMINANT)s-%(CONFIG_MODE)s'

The test map tells the test harness what parameters it should instantiate the
schema with, and what values those parameters should take. The test harness will
generate all possible permutations of input parameters, and will save them to
disk.

The test format is a string format (or a function taking a dictionary of
variable assignments) which will be used to name the test files
and test cases for this configuration.

Once you have all that, you can create a configuration context:

  config_ctx = config_item_context(FakeSchema, TEST_MAP, TEST_NAME_FORMAT)

config_ctx is a python decorator which you can use to create composable
configuration functions. For example:

  @config_ctx()
  def cool(c):
    if c.CONFIG_MODE == 'Happy':
      c.config_group.item_a = 100
    else:
      c.config_group.item_a = -100

  @config_ctx()
  def gnarly(c):
    c.extra_setting = 'gnarly!'

  @config_ctx(includes=('cool', 'gnarly'))
  def combo(c):
    if c.MAIN_DETERMINANT:
      c.config_group.item_b['nickname'] = 'purple'
      c.extra_setting += ' cows!'
    else:
      c.config_group.item_b['nickname'] = 'sad times'

If I now call:

  combo()

I will get back a configuraton object whose schema is FakeSchema, and whose
data is the accumulation of cool(), gnarly(), and combo(). I can continue to
manipulate this configuraton object, use its data, or render it to json.

Using this system should allow you to create rich, composible,
modular configurations. See the documentation on config_item_context and the
BaseConfig derivatives for more info.
"""

import collections
import functools
import types

class BadConf(Exception):
  pass

def config_item_context(CONFIG_SCHEMA, VAR_TEST_MAP, TEST_NAME_FORMAT,
                        TEST_FILE_FORMAT=None):
  """Create a configuration context.

  Args:
    CONFIG_SCHEMA: This is a function which can take a minimum of zero arguments
                   and returns an instance of BaseConfig. This BaseConfig
                   defines the schema for all configuration objects manipulated
                   in this context.
    VAR_TEST_MAP: A dict mapping arg_name to an iterable of values. This
                  provides the test harness with sufficient information to
                  generate all possible permutations of inputs for the
                  CONFIG_SCHEMA function.
    TEST_NAME_FORMAT: A string format (or function) for naming tests and test
                      expectation files. It will be formatted/called with a
                      dictionary of arg_name to value (using arg_names and
                      values generated from VAR_TEST_MAP)
    TEST_FILE_FORMAT: Similar to TEST_NAME_FORMAT, but for test files. Defaults
                      to TEST_NAME_FORMAT.

  Returns a config_ctx decorator for this context.
  """

  def config_ctx(group=None, includes=None, deps=None, no_test=False,
                 is_root=False, config_vars=None):
    """
    A decorator for functions which modify a given schema of configs.
    Examples continue using the schema and config_items defined in the module
    docstring.

    This decorator provides a series of related functions:
      * Any function decorated with this will be registered into this config
        context by __name__. This enables some of the other following features
        to work.
      * Alters the signature of the function so that it can recieve an extra
        parameter 'final'. See the documentation for final on inner().
      * Provides various convenience and error checking facilities.
        * In particular, this decorator will prevent you from calling the same
          config_ctx on a given config blob more than once (with the exception
          of setting final=False. See inner())

    Args:
      group(str) - Using this decorator with the `group' argument causes the
        decorated function to be a member of that group. Members of a group are
        mutually exclusive on the same configuration blob. For example, only
        one of these two functions could be applied to the config blob c:
          @config_ctx(group='a')
          def bob(c):
            c.extra_setting = "bob mode"

          @config_ctx(group='a')
          def bill(c):
            c.extra_setting = "bill mode"

      includes(iterable(str)) - Any config items named in the includes list will
        be run against the config blob before the decorated function can modify
        it. If an inclusion is already applied to the config blob, it's skipped
        without applying/raising BadConf. Example:
          @config_ctx(includes=('bob', 'cool'))
          def charlie(c):
            c.config_group.item_b = 25
        The result of this config_ctx (assuming default values for the schema)
        would be:
          {'config_group': { 'item_a': 100, 'item_b': 25 },
           'extra_setting': 'gnarly!'}

      deps(iterable(str)) - One or more groups which must be satisfied before
        this config_ctx can be applied to a config_blob. If you invoke
        a config_ctx on a blob without having all of its deps satisfied,
        you'll get a BadConf exception.

      no_test(bool) - If set to True, then this config_ctx will be skipped by
        the test harness. This defaults to (False or bool(deps)), since
        config_items with deps will never be satisfiable as the first
        config_ctx applied to a blob.

      is_root(bool) - If set to True on an item, this item will become the
        'basis' item for all other configurations in this group. That means that
        it will be implicitly included in all other config_items. There may only
        ever be one root item.

        Additionally, the test harness uses the root item to probe for invalid
        configuration combinations by running the root item first (if there is
        one), and skipping the configuration combination if the root config
        item throws BadConf.

      config_vars(dict) - A dictionary mapping of { CONFIG_VAR: <value> }. This
        sets the input contidions for the CONFIG_SCHEMA.

      Returns a new decorated version of this function (see inner()).
    """
    def decorator(f):
      name = f.__name__
      @functools.wraps(f)
      def inner(config=None, final=True, optional=False, **kwargs):
        """This is the function which is returned from the config_ctx
        decorator.

        It applies all of the logic mentioned in the config_ctx docstring
        above, and alters the function signature slightly.

        Args:
          config - The config blob that we intend to manipulate. This is passed
            through to the function after checking deps and including includes.
            After the function manipulates it, it is automatically returned.

          final(bool) - Set to True by default, this will record the application
            of this config_ctx to `config', which will prevent the config_ctx
            from being applied to `config' again. It also is used to see if the
            config blob satisfies deps for subsequent config_ctx applications
            (i.e. in order for a config_ctx to satisfy a dependency, it must
            be applied with final=True).

            This is useful to apply default values while allowing the config to
            later override those values.

            However, it's best if each config_ctx is final, because then you
            can implement the config items with less error checking, since you
            know that the item may only be applied once. For example, if your
            item appends something to a list, but is called with final=False,
            you'll have to make sure that you don't append the item twice, etc.

          **kwargs - Passed through to the decorated function without harm.

        Returns config and ignores the return value of the decorated function.
        """
        if config is None:
          config = config_ctx.CONFIG_SCHEMA()
        assert isinstance(config, ConfigGroup)
        inclusions = config._inclusions  # pylint: disable=W0212

        # inner.IS_ROOT will be True or False at the time of invocation.
        if (config_ctx.ROOT_CONFIG_ITEM and not inner.IS_ROOT and
            config_ctx.ROOT_CONFIG_ITEM.__name__ not in inclusions):
          config_ctx.ROOT_CONFIG_ITEM(config)

        if name in inclusions:
          if optional:
            return config
          raise BadConf('config_ctx "%s" is already in this config "%s"' %
                        (name, config.as_jsonish(include_hidden=True)))
        if final:
          inclusions.add(name)

        for include in (includes or []):
          if include in inclusions:
            continue
          try:
            config_ctx.CONFIG_ITEMS[include](config)
          except BadConf, e:
            raise BadConf('config "%s" includes "%s", but [%s]' %
                          (name, include, e))

        # deps are a list of group names. All groups must be represented
        # in config already.
        for dep_group in (deps or []):
          if not (inclusions & config_ctx.MUTEX_GROUPS[dep_group]):
            raise BadConf('dep group "%s" is unfulfilled for "%s"' %
                          (dep_group, name))

        if group:
          overlap = inclusions & config_ctx.MUTEX_GROUPS[group]
          overlap.discard(name)
          if overlap:
            raise BadConf('"%s" is a member of group "%s", but %s already ran' %
                          (name, group, tuple(overlap)))

        ret = f(config, **kwargs)
        assert ret is None, 'Got return value (%s) from "%s"?' % (ret, name)

        return config

      def default_config_vars():
        ret = {}
        for include in (includes or []):
          item = config_ctx.CONFIG_ITEMS[include]
          ret.update(item.DEFAULT_CONFIG_VARS())
        if config_vars:
          ret.update(config_vars)
        return ret
      inner.DEFAULT_CONFIG_VARS = default_config_vars

      assert name not in config_ctx.CONFIG_ITEMS
      config_ctx.CONFIG_ITEMS[name] = inner
      if group:
        config_ctx.MUTEX_GROUPS.setdefault(group, set()).add(name)
      inner.IS_ROOT = is_root
      if is_root:
        assert not config_ctx.ROOT_CONFIG_ITEM, (
          'may only have one root config_ctx!')
        config_ctx.ROOT_CONFIG_ITEM = inner
        inner.IS_ROOT = True
      inner.NO_TEST = no_test or bool(deps)
      return inner
    return decorator

  # Internal state and testing data
  config_ctx.I_AM_A_CONFIG_CTX = True
  config_ctx.CONFIG_ITEMS = {}
  config_ctx.MUTEX_GROUPS = {}
  config_ctx.CONFIG_SCHEMA = CONFIG_SCHEMA
  config_ctx.ROOT_CONFIG_ITEM = None
  config_ctx.VAR_TEST_MAP = VAR_TEST_MAP

  def formatter(obj, ext=None):
    '''Converts format obj to a function taking var assignments.

    Args:
      obj (str or fn(assignments)): If obj is a str, it will be % formatted
        with assignments (which is a dict of variables from VAR_TEST_MAP).
        Otherwise obj will be invoked with assignments, and expected to return
        a fully-rendered string.
      ext (None or str): Optionally specify an extension to enforce on the
        format. This enforcement occurs after obj is finalized to a string. If
        the string doesn't end with ext, it will be appended.
    '''
    def inner(var_assignments):
      ret = ''
      if isinstance(obj, basestring):
        ret = obj % var_assignments
      else:
        ret = obj(var_assignments)
      if ext and not ret.endswith(ext):
        ret += ext
      return ret
    return inner
  config_ctx.TEST_NAME_FORMAT = formatter(TEST_NAME_FORMAT)
  config_ctx.TEST_FILE_FORMAT = formatter(
    (TEST_FILE_FORMAT or TEST_NAME_FORMAT), ext='.json')
  return config_ctx


class ConfigBase(object):
  """This is the root interface for all config schema types."""

  def __init__(self, hidden=False):
    """
    Args:
      hidden - If set to True, this object will be excluded from printing when
        the config blob is rendered with ConfigGroup.as_jsonish(). You still
        have full read/write access to this blob otherwise though.
    """
    # work around subclasses which override __setattr__
    object.__setattr__(self, '_hidden', hidden)
    object.__setattr__(self, '_inclusions', set())

  def get_val(self):
    """Gets the native value of this config object."""
    return self

  def set_val(self, val):
    """Resets the value of this config object using data in val."""
    raise NotImplementedError

  def reset(self):
    """Resets the value of this config object to it's initial state."""
    raise NotImplementedError

  def as_jsonish(self, include_hidden=False):
    """Returns the value of this config object as simple types."""
    raise NotImplementedError

  def complete(self):
    """Returns True iff this configuraton blob is fully viable."""
    raise NotImplementedError


class ConfigGroup(ConfigBase):
  """Allows you to provide hierarchy to a configuration schema.

  Example usage:
    config_blob = ConfigGroup(
      some_item = SimpleConfig(str),
      group = ConfigGroup(
        numbahs = SetConfig(int),
      ),
    )
    config_blob.some_item = "hello"
    config_blob.group.numbahs.update(range(10))
  """

  def __init__(self, hidden=False, **type_map):
    """Expects type_map to be {python_name -> ConfigBase} instance."""
    super(ConfigGroup, self).__init__(hidden)
    assert type_map, 'A ConfigGroup with no type_map is meaningless.'

    object.__setattr__(self, '_type_map', type_map)
    for name, typeval in self._type_map.iteritems():
      assert isinstance(typeval, ConfigBase)
      object.__setattr__(self, name, typeval)

  def __getattribute__(self, name):
    obj = object.__getattribute__(self, name)
    if isinstance(obj, ConfigBase):
      return obj.get_val()
    else:
      return obj

  def __setattr__(self, name, val):
    obj = object.__getattribute__(self, name)
    assert isinstance(obj, ConfigBase)
    obj.set_val(val)

  def __delattr__(self, name):
    obj = object.__getattribute__(self, name)
    assert isinstance(obj, ConfigBase)
    obj.reset()

  def set_val(self, val):
    if isinstance(val, ConfigBase):
      val = val.as_jsonish(include_hidden=True)
    assert isinstance(val, dict)
    for name, config_obj in self._type_map.iteritems():
      if name in val:
        config_obj.set_val(val.pop())
    assert not val, "Got extra keys while setting ConfigGroup: %s" % val

  def as_jsonish(self, include_hidden=False):
    return dict(
      (n, v.as_jsonish(include_hidden)) for n, v in self._type_map.iteritems()
        if (include_hidden or not v._hidden))  # pylint: disable=W0212

  def reset(self):
    for v in self._type_map.values():
      v.reset()

  def complete(self):
    return all(v.complete() for v in self._type_map.values())


class ConfigList(ConfigBase, collections.MutableSequence):
  """Allows you to provide an ordered repetition to a configuration schema.

  Example usage:
    config_blob = ConfigGroup(
      some_items = ConfigList(
        ConfigGroup(
          herp = SimpleConfig(int),
          derp = SimpleConfig(str)
        )
      )
    )
    config_blob.some_items.append({'herp': 1})
    config_blob.some_items[0].derp = 'bob'
  """

  def __init__(self, item_schema, hidden=False):
    """
    Args:
      item_schema: The schema of each object. Should be a function which returns
                   an instance of ConfigGroup.
    """
    super(ConfigList, self).__init__(hidden=hidden)
    assert isinstance(item_schema, types.FunctionType)
    assert isinstance(item_schema(), ConfigGroup)
    self.item_schema = item_schema
    self.data = []

  def __getitem__(self, index):
    return self.data.__getitem__(index)

  def __setitem__(self, index, value):
    datum = self.item_schema()
    datum.set_val(value)
    return self.data.__setitem__(index, datum)

  def __delitem__(self, index):
    return self.data.__delitem__(index)

  def __len__(self):
    return len(self.data)

  def insert(self, index, value):
    datum = self.item_schema()
    datum.set_val(value)
    return self.data.insert(index, datum)

  def add(self):
    self.append({})
    return self[-1]

  def reset(self):
    self.data = []

  def complete(self):
    return all(i.complete() for i in self.data)

  def set_val(self, data):
    if isinstance(data, ConfigList):
      data = data.as_jsonish(include_hidden=True)
    assert isinstance(data, list)
    self.reset()
    for item in data:
      self.append(item)

  def as_jsonish(self, include_hidden=False):
    return [i.as_jsonish(include_hidden) for i in self.data
            if (include_hidden or not i._hidden)]  # pylint: disable=W0212


class Dict(ConfigBase, collections.MutableMapping):
  """Provides a semi-homogenous dict()-like configuration object."""

  def __init__(self, item_fn=lambda i: i, jsonish_fn=dict, value_type=None,
               hidden=False):
    """
    Args:
      item_fn - A function which renders (k, v) pairs to input items for
        jsonish_fn. Defaults to the identity function.
      jsonish_fn - A function which renders a list of outputs of item_fn to a
        JSON-compatiple python datatype. Defaults to dict().
      value_type - A type object used for constraining/validating the values
        assigned to this dictionary.
      hidden - See ConfigBase.
    """
    super(Dict, self).__init__(hidden)
    self.value_type = value_type
    self.item_fn = item_fn
    self.jsonish_fn = jsonish_fn
    self.data = {}

  def __getitem__(self, k):
    return self.data.__getitem__(k)

  def __setitem__(self, k, v):
    if self.value_type:
      assert isinstance(v, self.value_type)
    return self.data.__setitem__(k, v)

  def __delitem__(self, k):
    return self.data.__delitem__(k)

  def __iter__(self):
    return iter(self.data)

  def __len__(self):
    return len(self.data)

  def set_val(self, val):
    if isinstance(val, Dict):
      val = val.data
    assert isinstance(val, dict)
    assert all(isinstance(v, self.value_type) for v in val.itervalues())
    self.data = val

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(map(
      self.item_fn, sorted(self.data.iteritems(), key=lambda x: x[0])))

  def reset(self):
    self.data.clear()

  def complete(self):
    return True


class List(ConfigBase, collections.MutableSequence):
  """Provides a semi-homogenous list()-like configuration object."""

  def __init__(self, inner_type, jsonish_fn=list, hidden=False):
    """
    Args:
      inner_type - The type of data contained in this set, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the list() to a JSON-compatible
        python datatype. Defaults to list().
      hidden - See ConfigBase.
    """
    super(List, self).__init__(hidden)
    self.inner_type = inner_type
    self.jsonish_fn = jsonish_fn
    self.data = []

  def __getitem__(self, index):
    return self.data[index]

  def __setitem__(self, index, value):
    assert isinstance(value, self.inner_type)
    self.data[index] = value

  def __delitem__(self, index):
    del self.data

  def __len__(self):
    return len(self.data)

  def __radd__(self, other):
    if not isinstance(other, list):
      other = list(other)
    return other + self.data

  def insert(self, index, value):
    assert isinstance(value, self.inner_type)
    self.data.insert(index, value)

  def set_val(self, val):
    assert all(isinstance(v, self.inner_type) for v in val)
    self.data = list(val)

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(self.data)

  def reset(self):
    self.data = []

  def complete(self):
    return True


class Set(ConfigBase, collections.MutableSet):
  """Provides a semi-homogenous set()-like configuration object."""

  def __init__(self, inner_type, jsonish_fn=list, hidden=False):
    """
    Args:
      inner_type - The type of data contained in this set, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the set() to a JSON-compatible
        python datatype. Defaults to list().
      hidden - See ConfigBase.
    """
    super(Set, self).__init__(hidden)
    self.inner_type = inner_type
    self.jsonish_fn = jsonish_fn
    self.data = set()

  def __contains__(self, val):
    return val in self.data

  def __iter__(self):
    return iter(self.data)

  def __len__(self):
    return len(self.data)

  def add(self, value):
    assert isinstance(value, self.inner_type)
    self.data.add(value)

  def discard(self, value):
    self.data.discard(value)

  def set_val(self, val):
    assert all(isinstance(v, self.inner_type) for v in val)
    self.data = set(val)

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(sorted(self.data))

  def reset(self):
    self.data = set()

  def complete(self):
    return True


class Single(ConfigBase):
  """Provides a configuration object which holds a single 'simple' type."""

  def __init__(self, inner_type, jsonish_fn=lambda x: x, empty_val=None,
               required=True, hidden=False):
    """
    Args:
      inner_type - The type of data contained in this object, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the data to a JSON-compatible
        python datatype. Default is the identity function.
      emtpy_val - The value to use when initializing this object or when calling
        reset().
      required(bool) - True iff this config item is required to have a
        non-empty_val in order for it to be considered complete().
      hidden - See ConfigBase.
    """
    super(Single, self).__init__(hidden)
    self.inner_type = inner_type
    self.jsonish_fn = jsonish_fn
    self.empty_val = empty_val
    self.data = empty_val
    self.required = required

  def get_val(self):
    return self.data

  def set_val(self, val):
    if isinstance(val, Single):
      val = val.data
    assert val is self.empty_val or isinstance(val, self.inner_type)
    self.data = val

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(self.data)

  def reset(self):
    self.data = self.empty_val

  def complete(self):
    return not self.required or self.data is not self.empty_val


class Static(ConfigBase):
  """Holds a single, hidden, immutible data object.

  This is very useful for holding the 'input' configuration values (i.e. those
  which are in your VAR_TEST_MAP).
  """

  def __init__(self, value, hidden=True):
    super(Static, self).__init__(hidden=hidden)
    # Attempt to hash the value, which will ensure that it's immutable all the
    # way down :).
    hash(value)
    self.data = value

  def get_val(self):
    return self.data

  def set_val(self, val):
    assert False

  def as_jsonish(self, _include_hidden=None):
    return self.data

  def reset(self):
    assert False

  def complete(self):
    return True
