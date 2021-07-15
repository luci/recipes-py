# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import inspect

from future.utils import iteritems

from ..recipe_api import BoundProperty, PROPERTY_SENTINEL

from .exceptions import UndefinedPropertyException


def _invoke_with_properties(callable_obj, all_props, environ, prop_defs,
                            arg_names, **additional_args):
  """Internal version of invoke_with_properties.

  The main difference is it gets passed the argument names as `arg_names`.
  This allows us to reuse this logic elsewhere, without defining a fake function
  which has arbitrary argument names.
  """
  for name, prop in iteritems(prop_defs):
    if not isinstance(prop, BoundProperty):
      raise ValueError(
          "You tried to invoke {} with an unbound Property {} named {}".format(
              callable_obj, prop, name))

  # Maps parameter names to property names
  param_name_mapping = {
    prop.param_name: name for name, prop in iteritems(prop_defs)
  }

  props = []

  for param_name in arg_names:
    if param_name in additional_args:
      props.append(additional_args.pop(param_name))
      continue

    if param_name not in param_name_mapping:
      raise UndefinedPropertyException(
          "Missing property definition for parameter '{}'.".format(param_name))

    prop_name = param_name_mapping[param_name]

    if prop_name not in prop_defs:
      raise UndefinedPropertyException(
          "Missing property value for '{}'.".format(prop_name))

    prop = prop_defs[prop_name]
    props.append(
        prop.interpret(all_props.get(prop_name, PROPERTY_SENTINEL), environ))

  return callable_obj(*props, **additional_args)


def invoke_with_properties(callable_obj, all_props, environ, prop_defs,
                           **additional_args):
  """
  Invokes callable with filtered, type-checked properties.

  Args:
    callable_obj: The function to call, or class to instantiate.
                  This supports passing in either RunSteps, or a recipe module,
                  which is a class.
    all_props: A dictionary containing all the properties (strings) currently
               defined in the system.
    environ: A dictionary with environment to use for resolving 'from_environ'
             properties (usually os.environ, but replaced in tests).
    prop_defs: A dictionary of property name to property definitions
               (BoundProperty) for this callable.
    additional_args: kwargs to pass through to the callable.
                     Note that the names of the arguments can correspond to
                     positional arguments as well.

  Returns:
    The result of calling callable with the filtered properties
    and additional arguments.
  """
  # To detect when they didn't specify a property that they have as a
  # function argument, list the arguments, through inspection,
  # and then comparing this list to the provided properties. We use a list
  # instead of a dict because getargspec returns a list which we would have to
  # convert to a dictionary, and the benefit of the dictionary is pretty small.
  if inspect.isclass(callable_obj):
    arg_names = inspect.getargspec(callable_obj.__init__).args
    arg_names.pop(0)  # 'self'
  else:
    arg_names = inspect.getargspec(callable_obj).args
  return _invoke_with_properties(callable_obj, all_props, environ, prop_defs,
                                 arg_names, **additional_args)
