# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This module defines `StepData` which is the object returned from executing
a single step (subprocess), usually via the `recipe_engine/step` recipe module.
"""

from future.utils import iteritems, itervalues
from past.builtins import basestring

import attr

from .internal.attr_util import attr_type

from .engine_types import StepPresentation


@attr.s
class _AttributeRaiser(object):
  _step_name = attr.ib(validator=attr_type(basestring))
  _namespace = attr.ib(validator=attr_type(str))
  # `_finalized` doesn't use `attr.s` because of the shenanigans we do with
  # `__getattr__`.

  def __getattr__(self, name):
    raise AttributeError('StepData(%r)%s has no attribute %r.' % (
      self._step_name, self._namespace, name))

  def __setattr__(self, name, value):
    # Directly access the instance's __dict__ since this logic is called during
    # __init__ and _finalized may not actually be set yet. Calling
    # hasattr/getattr will result in __getattr__ being called which will fail
    # because it accesses `self._step_name` and `self._namespace` which ALSO
    # might not exist yet.
    if not self.__dict__.get('_finalized', False):
      return object.__setattr__(self, name, value)

    raise AttributeError('Cannot assign to StepData(%r)%s.%s' % (
      self._step_name, self._namespace, name))


@attr.s(frozen=True)
class ExecutionResult(object):
  # retcode is the integer returncode of the step, if the step ran and the
  # engine was able to wait() for it. Otherwise this is None.
  retcode = attr.ib(validator=attr_type((int, type(None))), default=None)

  # had_exception is set to True if this step had some exceptional circumstance
  # which prevented it from running, or a failure while evaluating the output
  # Placeholders for this step. e.g.
  #   * Failed to resolve cmd0 / executable doesn't exist
  #   * Input placeholders raised an exception prior to running the step
  #   * Output placeholders raised an exception after running the step
  had_exception = attr.ib(validator=attr_type(bool), default=False)

  # had_timeout is only set to True if this specific step had a timeout
  # requested for it.
  #
  # Steps killed due to e.g. LUCI_CONTEXT['deadline'] will have `was_cancelled`
  # set to True instead.
  had_timeout = attr.ib(validator=attr_type(bool), default=False)

  # was_cancelled is set if the step was canceled by:
  #   * GLOBAL_SHUTDOWN due to an interrupt signal from outside
  #     the recipe engine or due to the engine hitting it's
  #     LUCI_CONTEXT['deadline']['soft_deadline']
  #   * The step being part of a greenlet which is kill'd via
  #     Future.cancel().
  was_cancelled = attr.ib(validator=attr_type(bool), default=False)


@attr.s
class StepData(object):
  """StepData represents the result of running a step.

  For historical reasons, this object has dynamic properties depending on the
  OutputPlaceholders used with the step.

  Every Placeholder has a 'namespace', which is a tuple consisting of the recipe
  module name and function name from however the placeholder was created. For
  example, the namespace of a `api.json.output(...)` placeholder is ('json',
  'output').

  Somewhat confusingly, Placeholders can also have a 'name', which is set by the
  user (like "script_data").

  The namespace and the name are used by the engine to assign the result of the
  Placeholder into this StepData object at a number of places:

    * If the placeholder does not have a name, then the namespace is used to
      assign into the StepData like `StepData.namespace.part = result`. It's not
      valid to have two nameless placeholders with the same namespace.
    * If the placeholder DOES have a name, then it's assigned to (note the `s`
      on `parts`):

      StepData.namespace.parts[name] = result

    * Additionally, if there's exactly one named placeholder, then it's result
      is also assigned to `StepData.namespace.part`.

  # TODO(iannucci): This is all rubbish; change this so that:
  #   * All placeholders are given an explicit name by the caller.
  #   * All placeholder results are mapped to StepData.placeholders[name].
  #   * Remove 'clever' dynamic assignment and _AttributeRaiser.

  Example 1:

      // Input
      api.step('...', ['...', api.json.output()])

      // Output
      StepData.json.output = json.output().result()
      StepData.json.outputs = {}

  Example 2:

      // Input
      api.step('...', ['...', api.json.output(), api.other.placeholder()])

      // Output
      StepData.json.output = json.output().result()
      StepData.json.outputs = {}
      StepData.json.placeholder = other.placeholder().result()
      StepData.json.placeholders = {}

  Example 3:

      // Input
      api.step('...', ['...', api.json.output(), api.json.output()])

      // Invalid; two unnamed placeholders with the same namespace

  Example 4:

      // Input
      api.step('...', ['...', api.json.output(name='bob')])

      // Output
      StepData.json.output = json.output(name='bob').result()
      StepData.json.outputs = {'bob': json.output(name='bob').result()}

  Example 5:

      // Input
      api.step('...', ['...', api.json.output(name='bob'), api.json.output()])

      // Output
      StepData.json.output = json.output().result()
      StepData.json.outputs = {'bob': json.output(name='bob').result()}

  Example 6:

      // Input
      api.step('...', ['...', api.json.output(name='bob'),
                              api.json.output(name='charlie')])

      // Output
      # No 'json.output' because they all have names, and there's more than one
      # with a name.
      StepData.json.outputs = {
        'bob': json.output(name='bob')
        'charlie': json.output(name='charlie')
      }
  """
  # The name of this step as a tuple of strings.
  #
  # Each entry in the tuple represents a nesting namespace, and the final value
  # in the tuple represents the step's leaf name.
  #
  # Example:
  #
  #    ('step name')             # a top level step
  #    ('parent', 'step name')   # a step named "step name" under "parent"
  name_tokens = attr.ib(validator=attr_type(tuple))

  # The execution result of the step.
  exc_result = attr.ib(validator=attr_type(ExecutionResult))

  # The result of the `stdout` Placeholder, if the step had one.
  #
  # Unless you set the `stdout` kwarg when running the step, this will be None.
  stdout = attr.ib(default=None)

  # The result of the `stderr` Placeholder, if the step had one.
  #
  # Unless you set the `stderr` kwarg when running the step, this will be None.
  stderr = attr.ib(default=None)

  # Dict[
  #   namespace: Tuple[str],
  #   Dict[
  #     name: str,
  #     result: object]]
  #
  # namespace tuple: the tuple of namespace strings for this placeholder. e.g.
  #   `('json', 'output')`.
  # name: the "name" of the placeholder (within its namespace) or None for
  #   an unnamed placeholder. The name is user-specified to disambiguate between
  #   multiple placeholders in the same namespace on the same step (e.g.
  #   multiple `json.output()`).
  # result: Anything the OutputPlaceholder.result() method returned.
  _staged_placeholders = attr.ib(
      validator=attr_type(dict, type(None)), factory=dict)

  # When set to True, all future assignments to this object are prevented.
  _finalized = attr.ib(validator=attr_type(bool), default=False)

  @property
  def name(self):
    """Returns the build.proto step name (i.e. name_tokens joined with '|')."""
    return '|'.join(self.name_tokens)

  @property
  def retcode(self):
    """DEPRECATED: use .exc_result directly."""
    return self.exc_result.retcode

  def _populate_placeholders(self):
    """
    """
    if self._finalized:
      return

    # Grab all staged placeholders, set _staged_placeholders to None so that no
    # more placeholders could be staged.
    staged = self._staged_placeholders
    self._staged_placeholders = None

    # If we don't have any work, return
    if not staged:
      return

    def _deep_set(namespace, value):
      """Sets `value` at `namespace` on self.

      Populates intermediate tiers of namespace with _AttributeRaiser objects.

      Args:
        * namespace (Tuple[str]) - A tuple of python identifiers. e.g.
          `('json', 'output')`.
        * value (object) - Arbitrary data to set at the given namespace.
      """
      last_token = namespace[-1]

      obj = self
      namespace_so_far = ''
      for part in namespace[:-1]:
        namespace_so_far += '.%s' % part
        if not hasattr(obj, part):
          subval = _AttributeRaiser(self.name, namespace_so_far)
          setattr(obj, part, subval)
        else:
          subval = getattr(obj, part)
        obj = subval

      setattr(obj, last_token, value)


    # A singleton object used in the loop below to indicate that a data item was
    # not set. Pylint is dumb and doesn't like uppercase function variables.
    UNSET = object()   # pylint: disable=invalid-name

    # For every staged placeholder namespace.
    for namespace, name_to_result in iteritems(staged):
      # The default is defined as the result from the Placeholder with no name
      default = name_to_result.pop(None, UNSET)
      # OR the Placeholder (if there was only one in this namespace)
      if default is UNSET and len(name_to_result) == 1:
        default = list(itervalues(name_to_result))[0]
      if default is not UNSET:
        # This sets e.g. 'json.output' to `default`
        _deep_set(namespace, default)

      if name_to_result:
        # This sets e.g. 'json.outputs' to
        #   {"user_provided_name": value, "other_name": other_value}
        plural_namespace = namespace[:-1] + (namespace[-1] + 's',)
        _deep_set(plural_namespace, name_to_result)

    # Now set `_finalized` on all _AttributeRaiser objects to prevent further
    # assignments.
    objs = list(itervalues(self.__dict__))
    while objs:
      obj = objs.pop()
      if not isinstance(obj, _AttributeRaiser):
        continue
      objs.extend(itervalues(obj.__dict__))
      obj._finalized = True   # pylint: disable=protected-access

  def finalize(self):
    """Fills all user-accessible placeholder results, and prevents accidental
    assignment to this StepData.

    Used by the Recipe Engine. You don't need to worry about this :)
    """
    if self._finalized:
      return

    self._populate_placeholders()
    self._finalized = True

  def assign_placeholder(self, placeholder, result):
    """Used by the Recipe Engine to stage placeholder data in this StepData.

    May only be called on a non-finalized StepData instance.

    The placeholder will become user-accessible once this StepData is finalized.

    Args:
      * placeholder (Placeholder) - The placeholder instance to stage. This
        function extracts the namespaces and name.
      * result (object) - The final result of this placeholder.
    """
    if self._finalized:
      raise ValueError(
          'Cannot assign placeholder %r (%r) on finalized StepData from step %r'
          % (placeholder.namespaces, placeholder.name, self.name))
    self._staged_placeholders.setdefault(
        placeholder.namespaces, {})[placeholder.name] = result

  def __setattr__(self, name, value):
    # Directly access the instance's __dict__ since this logic is called during
    # __init__ and _finalized may not actually be set yet. Calling
    # hasattr/getattr will result in __getattr__ being called which will fail
    # because it accesses `self.name` which ALSO might not exist yet.
    if self.__dict__.get('_finalized', False):
      raise ValueError('Cannot assign to %r on finalized StepData from step %r'
                       % (name, self.name))
    return object.__setattr__(self, name, value)

  def __getattr__(self, name):
    try:
      return object.__getattribute__(self, name)
    except AttributeError:
      raise AttributeError(
          'StepData from step %r has no attribute %r.' % (self.name, name))
