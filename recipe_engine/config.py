# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

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
python data), but also provides type checking and type conversion assistance
(so you can easily render your configurations to JSON).

Then you can create a configuration context:

  config_ctx = config_item_context(FakeSchema)

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

I will get back a configuration object whose schema is FakeSchema, and whose
data is the accumulation of cool(), gnarly(), and combo(). I can continue to
manipulate this configuration object, use its data, or render it to json.

Using this system should allow you to create rich, composible, modular
configurations. See the documentation on config_item_context and the BaseConfig
derivatives for more info.
"""

from builtins import object
from past.builtins import basestring

import collections.abc
import functools
import json
import types

from PB.recipe_engine import doc
from recipe_engine.config_types import Path

class BadConf(Exception):
  pass

def typeAssert(obj, typearg):
  if not isinstance(obj, typearg):
    raise TypeError("Expected %r to be of type %r" % (obj, typearg))

class ConfigContext:
  """A configuration context for a recipe module.

  Holds configuration schema and also acts as a config_ctx decorator.
  A recipe module can define at most one such context.
  """

  def __init__(self, CONFIG_SCHEMA):
    self.CONFIG_ITEMS = {}
    self.MUTEX_GROUPS = {}
    self.CONFIG_SCHEMA = CONFIG_SCHEMA
    self.ROOT_CONFIG_ITEM = None

  def __call__(self, group=None, includes=None, deps=None, is_root=False):
    """
    A decorator for functions which modify a given schema of configs.
    Examples continue using the schema and config_items defined in the module
    docstring.

    This decorator provides a series of related functions:
      * Any function decorated with this will be registered into this config
        context by __name__. This enables some of the other following features
        to work.
      * Alters the signature of the function so that it can receive an extra
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

      is_root(bool) - If set to True on an item, this item will become the
        'basis' item for all other configurations in this group. That means that
        it will be implicitly included in all other config_items. There may only
        ever be one root item.

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
          config = self.CONFIG_SCHEMA()
        assert isinstance(config, ConfigGroup)
        inclusions = config._inclusions  # pylint: disable=W0212

        # inner.IS_ROOT will be True or False at the time of invocation.
        if (self.ROOT_CONFIG_ITEM and not inner.IS_ROOT and
            self.ROOT_CONFIG_ITEM.__name__ not in inclusions):
          self.ROOT_CONFIG_ITEM(config)

        if name in inclusions:
          if optional:
            return config
          raise BadConf('config_ctx "%s" is already in this config "%s"' %
                        (name, config.as_jsonish(include_hidden=True)))
        if final:
          inclusions.add(name)

        for include in includes or []:
          if include in inclusions:
            continue
          try:
            self.CONFIG_ITEMS[include](config)
          except BadConf as e:
            raise BadConf('config "%s" includes "%s", but [%s]' %
                          (name, include, e))

        # deps are a list of group names. All groups must be represented
        # in config already.
        for dep_group in deps or []:
          if not inclusions & self.MUTEX_GROUPS[dep_group]:
            raise BadConf('dep group "%s" is unfulfilled for "%s"' %
                          (dep_group, name))

        if group:
          overlap = inclusions & self.MUTEX_GROUPS[group]
          overlap.discard(name)
          if overlap:
            raise BadConf('"%s" is a member of group "%s", but %s already ran' %
                          (name, group, tuple(overlap)))

        ret = f(config, **kwargs)
        assert ret is None, 'Got return value (%s) from "%s"?' % (ret, name)

        return config
      inner.WRAPPED = f
      inner.INCLUDES = includes or []

      assert name not in self.CONFIG_ITEMS, (
          '%s is already in CONFIG_ITEMS' % name)
      self.CONFIG_ITEMS[name] = inner
      if group:
        self.MUTEX_GROUPS.setdefault(group, set()).add(name)
      inner.IS_ROOT = is_root
      if is_root:
        assert not self.ROOT_CONFIG_ITEM, (
          'may only have one root config_ctx!')
        self.ROOT_CONFIG_ITEM = inner
        inner.IS_ROOT = True
      return inner
    return decorator


def config_item_context(CONFIG_SCHEMA):
  """Create a configuration context.

  Args:
    CONFIG_SCHEMA: This is a function which can take a minimum of zero arguments
                   and returns an instance of BaseConfig. This BaseConfig
                   defines the schema for all configuration objects manipulated
                   in this context.

  Returns a config_ctx decorator for this context.
  """
  return ConfigContext(CONFIG_SCHEMA)


class AutoHide:
  pass
AutoHide = AutoHide()


class ConfigBase:
  """This is the root interface for all config schema types."""

  def __init__(self, hidden=AutoHide):
    """
    Args:
      hidden -
        True: This object will be excluded from printing when the config blob
              is rendered with ConfigGroup.as_jsonish(). You still have full
              read/write access to this blob otherwise though.
        False: This will be printed as part of ConfigGroup.as_jsonish()
        AutoHide: This will be printed as part of ConfigGroup.as_jsonish() only
              if self._is_default() is false.
    """
    # work around subclasses which override __setattr__
    object.__setattr__(self, '_hidden_mode', hidden)
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
    """Returns True iff this configuration blob is fully viable."""
    raise NotImplementedError

  def _is_default(self):
    """Returns True iff this configuration blob is the default value."""
    raise NotImplementedError

  @property
  def _hidden(self):
    """Returns True iff this configuration blob is hidden."""
    if self._hidden_mode is AutoHide:
      return self._is_default()
    return self._hidden_mode

  def schema_proto(self):
    """Returns a doc.Doc.Schema proto message for this config type."""
    raise NotImplementedError

# TODO(crbug.com/1147793): Remove basestring mapping after we drop
# Single(basestring) support in all downstream repos.
_SIMPLE_TYPE_LOOKUP = {
  str: doc.Doc.Schema.STRING,
  basestring: doc.Doc.Schema.STRING,
  int: doc.Doc.Schema.NUMBER,
  float: doc.Doc.Schema.NUMBER,
  bool: doc.Doc.Schema.BOOLEAN,
  dict: doc.Doc.Schema.OBJECT,
  list: doc.Doc.Schema.ARRAY,
  type(None): doc.Doc.Schema.NULL,
  bytes: doc.Doc.Schema.STRING,
}


def _inner_type_schema(inner_type):
  ret = []
  def _flatten(typ):
    if isinstance(typ, collections.abc.Iterable):
      for subtyp in typ:
        _flatten(subtyp)
    else:
      ret.append(_SIMPLE_TYPE_LOOKUP[typ])
  _flatten(inner_type)
  return sorted(set(ret))


class ConfigSchemaBase:
  """
  A ConfigSchema is an immutable object whose only purpose is to define a
  particular schema which can be re-used many times with no re-use issues.
  It generates a mutable, bound version of the schema it represents, using the
  mutable config objects such as ConfigGroup.
  """
  def bind(self, value):
    """
    Type check the value, and generate a resulting mutable object representation
    of this value.
    """
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

  def __init__(self, hidden=AutoHide, **type_map):
    """Expects type_map to be {python_name -> ConfigBase} instance."""
    super().__init__(hidden)
    assert type_map, 'A ConfigGroup with no type_map is meaningless.'

    object.__setattr__(self, '_type_map', type_map)
    for name, typeval in self._type_map.items():
      typeAssert(typeval, ConfigBase)
      object.__setattr__(self, name, typeval)

  def __getattribute__(self, name):
    obj = object.__getattribute__(self, name)
    if isinstance(obj, ConfigBase):
      return obj.get_val()
    else:
      return obj

  def __setattr__(self, name, val):
    obj = object.__getattribute__(self, name)
    typeAssert(obj, ConfigBase)
    obj.set_val(val)

  def __delattr__(self, name):
    obj = object.__getattribute__(self, name)
    typeAssert(obj, ConfigBase)
    obj.reset()

  def set_val(self, val):
    if isinstance(val, ConfigBase):
      val = val.as_jsonish(include_hidden=True)
    typeAssert(val, collections.abc.Mapping)

    val = dict(val)  # because we pop later.
    for name, config_obj in self._type_map.items():
      if name in val:
        try:
          config_obj.set_val(val.pop(name))
        except Exception as e:
          raise type(e)('While assigning key %r: %s' % (name, e))

    if val:
      raise TypeError("Got extra keys while setting ConfigGroup: %s" % val)

  def as_jsonish(self, include_hidden=False):
    return dict(
      (n, v.as_jsonish(include_hidden)) for n, v in self._type_map.items()
        if include_hidden or not v._hidden)  # pylint: disable=W0212

  def reset(self):
    for v in self._type_map.values():
      v.reset()

  def complete(self):
    return all(v.complete() for v in self._type_map.values())

  def _is_default(self):
    # pylint: disable=W0212
    return all(v._is_default() for v in self._type_map.values())

  def schema_proto(self):
    ret = doc.Doc.Schema()
    for k, v in self._type_map.items():
      ret.struct.type_map[k].CopyFrom(v.schema_proto())
    return ret


class ConfigGroupSchema(ConfigSchemaBase):
  """
  A small class which provides an immutable schema which generates ConfigGroups
  from the schema, given some values. Used for return values in the recipe
  engine system, because if a script gets loaded more than once, we don't want
  any leftover values in the return ConfigGroup.
  """

  def __init__(self, **type_map):
    """Expects type_map to be {python_name -> ConfigBase} instance."""
    super().__init__()
    if not type_map:
      raise ValueError('A ConfigGroup with no type_map is meaningless.')

    object.__setattr__(self, '_type_map', type_map)
    for _, typeval in self._type_map.items():
      typeAssert(typeval, ConfigBase)

  def __call__(self, *args, **kwargs):
    return self.new(*args, **kwargs)

  def new(self, **kwargs):
    """Generates a ConfigGroup with my type map and the given values."""
    cfg = ConfigGroup(**self._type_map)
    cfg.set_val(kwargs)
    return cfg

  def schema_proto(self):
    ret = doc.Doc.Schema()
    for k, v in self._type_map.items():
      ret.struct.type_map[k].CopyFrom(v.schema_proto())
    return ret


ReturnSchema = ConfigGroupSchema


class ConfigList(ConfigBase, collections.abc.MutableSequence):
  """Allows you to provide an ordered repetition to a configuration schema.

  Example usage:
    config_blob = ConfigGroup(
      some_items = ConfigList(
        lambda: ConfigGroup(
          herp = Single(int),
          derp = Single(str)
        )
      )
    )
    config_blob.some_items.append({'herp': 1})
    config_blob.some_items[0].derp = 'bob'
  """

  def __init__(self, item_schema, hidden=AutoHide):
    """
    Args:
      item_schema: The schema of each object. Should be a function which returns
                   an instance of ConfigGroup.
    """
    super().__init__(hidden=hidden)
    typeAssert(item_schema, types.FunctionType)
    typeAssert(item_schema(), ConfigGroup)
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

    typeAssert(data, list)
    self.reset()
    for item in data:
      self.append(item)

  def as_jsonish(self, include_hidden=False):
    return [i.as_jsonish(include_hidden) for i in self.data
            if include_hidden or not i._hidden]  # pylint: disable=W0212

  def _is_default(self):
    # pylint: disable=W0212
    return all(v._is_default() for v in self.data)

  def schema_proto(self):
    ret = doc.Doc.Schema()
    ret.sequence.inner_type.CopyFrom(self.item_schema().schema_proto())
    return ret


class Dict(ConfigBase, collections.abc.MutableMapping):
  """Provides a semi-homogenous dict()-like configuration object."""

  def __init__(self, item_fn=lambda i: i, jsonish_fn=dict, value_type=None,
               hidden=AutoHide):
    """
    Args:
      item_fn - A function which renders (k, v) pairs to input items for
        jsonish_fn. Defaults to the identity function.
      jsonish_fn - A function which renders a list of outputs of item_fn to a
        JSON-compatiple python datatype. Defaults to dict().
      value_type - A type object used for constraining/validating the values
        assigned to this dictionary. If None, the value can be any type.
      hidden - See ConfigBase.
    """
    super().__init__(hidden)
    self.value_type = value_type
    self.item_fn = item_fn
    self.jsonish_fn = jsonish_fn
    self.data = {}

  def __getitem__(self, k):
    return self.data.__getitem__(k)

  def __setitem__(self, k, v):
    if self.value_type:
      typeAssert(v, self.value_type)
    return self.data.__setitem__(k, v)

  def __delitem__(self, k):
    return self.data.__delitem__(k)

  def __iter__(self):
    return iter(self.data)

  def __len__(self):
    return len(self.data)

  def __repr__(self):
    return repr(self.data)

  def __str__(self):
    return str(self.data)

  def set_val(self, val):
    if isinstance(val, Dict):
      val = val.data
    typeAssert(val, collections.abc.Mapping)
    if self.value_type:
      for v in val.values():
        typeAssert(v, self.value_type)
    self.data = val

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn([
      self.item_fn(item)
      for item in sorted(self.data.items(), key=lambda x: x[0])
    ])

  def reset(self):
    self.data.clear()

  def complete(self):
    return True

  def _is_default(self):
    return not self.data

  def schema_proto(self):
    ret = doc.Doc.Schema()
    if self.value_type is not None:
      ret.dict.value_type.extend(_inner_type_schema(self.value_type))
    return ret


class List(ConfigBase, collections.abc.MutableSequence):
  """Provides a semi-homogenous list()-like configuration object."""

  def __init__(self, inner_type, jsonish_fn=list, hidden=AutoHide):
    """
    Args:
      inner_type - The type of data contained in this set, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the list() to a JSON-compatible
        python datatype. Defaults to list().
      hidden - See ConfigBase.
    """
    super().__init__(hidden)
    self.inner_type = inner_type
    self.jsonish_fn = jsonish_fn
    self.data = []

  def __getitem__(self, index):
    return self.data[index]

  def __setitem__(self, index, value):
    typeAssert(value, self.inner_type)
    self.data[index] = value

  def __delitem__(self, index):
    del self.data[index]

  def __len__(self):
    return len(self.data)

  def __radd__(self, other):
    if not isinstance(other, list):
      other = list(other)
    return other + self.data

  def insert(self, index, value):
    typeAssert(value, self.inner_type)
    self.data.insert(index, value)

  def set_val(self, val):
    for v in val:
      typeAssert(v, self.inner_type)
    self.data = list(val)

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(self.data)

  def reset(self):
    self.data = []

  def complete(self):
    return True

  def _is_default(self):
    return not self.data

  def schema_proto(self):
    ret = doc.Doc.Schema()
    ret.list.inner_type.extend(_inner_type_schema(self.inner_type))
    return ret


class Set(ConfigBase, collections.abc.MutableSet):
  """Provides a semi-homogenous set()-like configuration object."""

  def __init__(self, inner_type, jsonish_fn=list, hidden=AutoHide):
    """
    Args:
      inner_type - The type of data contained in this set, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the set() to a JSON-compatible
        python datatype. Defaults to list().
      hidden - See ConfigBase.
    """
    super().__init__(hidden)
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
    typeAssert(value, self.inner_type)
    self.data.add(value)

  def update(self, values):
    for value in values:
      if value not in self:
        self.add(value)

  def discard(self, value):
    self.data.discard(value)

  def set_val(self, val):
    for v in val:
      typeAssert(v, self.inner_type)
    self.data = set(val)

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(sorted(self.data))

  def reset(self):
    self.data = set()

  def complete(self):
    return True

  def _is_default(self):
    return not self.data

  def schema_proto(self):
    ret = doc.Doc.Schema()
    ret.set.inner_type.extend(_inner_type_schema(self.inner_type))
    return ret


class Single(ConfigBase):
  """Provides a configuration object which holds a single 'simple' type."""

  def __init__(self, inner_type, jsonish_fn=lambda x: x, empty_val=None,
               required=True, hidden=AutoHide):
    """
    Args:
      inner_type - The type of data contained in this object, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the data to a JSON-compatible
        python datatype. Default is the identity function.
      empty_val - The value to use when initializing this object or when calling
        reset().
      required(bool) - True iff this config item is required to have a
        non-empty_val in order for it to be considered complete().
      hidden - See ConfigBase.
    """
    super().__init__(hidden)
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
    if val is not self.empty_val:
      typeAssert(val, self.inner_type)
    self.data = val

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(self.data)

  def reset(self):
    self.data = self.empty_val

  def complete(self):
    return not self.required or self.data is not self.empty_val

  def _is_default(self):
    return self.data is self.empty_val

  def schema_proto(self):
    ret = doc.Doc.Schema()
    ret.single.inner_type.extend(_inner_type_schema(self.inner_type))
    ret.single.required = self.required
    ret.single.default_json = json.dumps(self.jsonish_fn(self.empty_val))
    return ret


class Static(ConfigBase):
  """Holds a single, hidden, immutable data object.

  This is very useful for holding the 'input' configuration values.
  """

  def __init__(self, value, hidden=AutoHide):
    super().__init__(hidden=hidden)
    # HACK: Paths are functionally immutable, but cannot have their __hash__
    # execute correctly until the checkout_dir has actually been set (because
    # the __hash__ implementation when a Path is based on checkout_dir wants to
    # compute a result identical to the real underlying Path).
    #
    # Since we plan to entirely remove all of this config.py contents at some
    # point, and Paths are the only known exception to the immutability rule
    # with well-understood semantics we have a special carve-out here.
    if isinstance(value, Path):
      pass
    else:
      # Attempt to hash the value, which will ensure that it's immutable all the
      # way down :).
      hash(value)
    self.data = value

  def get_val(self):
    return self.data

  def set_val(self, val):
    raise TypeError("Cannot assign to a Static config member")

  def as_jsonish(self, _include_hidden=None):
    return self.data

  def reset(self):
    assert False

  def complete(self):
    return True

  def _is_default(self):
    return True

  def schema_proto(self):
    ret = doc.Doc.Schema()
    ret.static.default_json = json.dumps(self.data)
    return ret


class Enum(ConfigBase):
  """Provides a configuration object which holds one of acceptable values."""

  def __init__(self, *values, **kwargs):
    """
    Args:
      values - List of acceptable values.
      inner_type - The type of data contained in this object, e.g. str, int, ...
        Can also be a tuple of types to allow more than one type.
      jsonish_fn - A function used to reduce the data to a JSON-compatible
        python datatype. Default is the identity function.
      required(bool) - True iff this config item is required to have a
        value in order for it to be considered complete().
      hidden - See ConfigBase.
    """
    super().__init__(kwargs.get('hidden', AutoHide))
    if not values:
      raise ValueError("Enumerations cannot be empty")
    self.values = values
    self.inner_type = kwargs.get('inner_type', basestring)
    self.jsonish_fn = kwargs.get('jsonish_fn', lambda x: x)
    self.data = None
    self.required = kwargs.get('required', True)

  def get_val(self):
    return self.data

  def set_val(self, val):
    if isinstance(val, Enum):
      val = val.data
    typeAssert(val, self.inner_type)
    if not val in self.values:
      raise ValueError("Expected %r to be one of %r" %
                       (val, ', '.join(self.values)))
    self.data = val

  def as_jsonish(self, _include_hidden=None):
    return self.jsonish_fn(self.data)

  def reset(self):
    self.data = None

  def complete(self):
    return not self.required or self.data is not None

  def _is_default(self):
    return self.data is None

  def schema_proto(self):
    ret = doc.Doc.Schema()
    ret.enum.values_json.extend(json.dumps(self.jsonish_fn(v))
                                for v in self.values)
    ret.enum.required = self.required
    return ret
