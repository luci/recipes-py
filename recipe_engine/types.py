# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import copy
import json
import operator

from .internal.engine_step import StepConfig


def freeze(obj):
  """Takes a generic object ``obj``, and returns an immutable version of it.

  Supported types:
    * dict / OrderedDict -> FrozenDict
    * list -> tuple
    * set -> frozenset
    * any object with a working __hash__ implementation (assumes that hashable
      means immutable)

  Will raise TypeError if you pass an object which is not hashable.
  """
  if isinstance(obj, dict):
    return FrozenDict((freeze(k), freeze(v)) for k, v in obj.iteritems())
  elif isinstance(obj, (list, tuple)):
    return tuple(freeze(i) for i in obj)
  elif isinstance(obj, set):
    return frozenset(freeze(i) for i in obj)
  else:
    hash(obj)
    return obj


def thaw(obj):
  """Takes a a frozen object, and returns a mutable version of it.

  Conversions:
    * collections.Mapping -> dict
    * tuple -> list
    * frozenset -> set

  Close to the opposite of freeze().
  Does not convert dict keys.
  """
  if isinstance(obj, (dict, collections.OrderedDict, FrozenDict)):
    return {k: thaw(v) for k, v in obj.iteritems()}
  elif isinstance(obj, (list, tuple)):
    return [thaw(i) for i in obj]
  elif isinstance(obj, (set, frozenset)):
    return {thaw(i) for i in obj}
  else:
    return obj


class FrozenDict(collections.Mapping):
  """An immutable OrderedDict.

  Modified From: http://stackoverflow.com/a/2704866
  """
  def __init__(self, *args, **kwargs):
    self._d = collections.OrderedDict(*args, **kwargs)

    # If getitem would raise a KeyError, then call this function back with the
    # missing key instead. This should raise an exception. If the function
    # returns, the original KeyError will be raised.
    self.on_missing = lambda key: None

    # Calculate the hash immediately so that we know all the items are
    # hashable too.
    self._hash = reduce(operator.xor,
                        (hash(i) for i in enumerate(self._d.iteritems())), 0)

  def __eq__(self, other):
    if not isinstance(other, collections.Mapping):
      return NotImplemented
    if self is other:
      return True
    if len(self) != len(other):
      return False
    for k, v in self.iteritems():
      if k not in other or other[k] != v:
        return False
    return True

  def __iter__(self):
    return iter(self._d)

  def __len__(self):
    return len(self._d)

  def __getitem__(self, key):
    try:
      return self._d[key]
    except KeyError:
      self.on_missing(key)
      raise

  def __hash__(self):
    return self._hash

  def __repr__(self):
    return 'FrozenDict(%r)' % (self._d.items(),)


class StepPresentation(object):
  STATUSES = set(('SUCCESS', 'FAILURE', 'WARNING', 'EXCEPTION'))

  def __init__(self, step_name):
    self._name = step_name
    self._finalized = False

    self._logs = collections.OrderedDict()
    self._links = collections.OrderedDict()
    self._status = None
    self._step_summary_text = ''
    self._step_text = ''
    self._properties = {}

  # (E0202) pylint bug: http://www.logilab.org/ticket/89092
  @property
  def status(self):  # pylint: disable=E0202
    return self._status

  @status.setter
  def status(self, val):  # pylint: disable=E0202
    assert not self._finalized, 'Changing finalized step %r' % self._name
    assert val in self.STATUSES
    self._status = val

  @property
  def step_text(self):
    return self._step_text

  @step_text.setter
  def step_text(self, val):
    assert not self._finalized, 'Changing finalized step %r' % self._name
    self._step_text = val

  @property
  def step_summary_text(self):
    return self._step_summary_text

  @step_summary_text.setter
  def step_summary_text(self, val):
    assert not self._finalized, 'Changing finalized step %r' % self._name
    self._step_summary_text = val

  @property
  def logs(self):
    assert not self._finalized, 'Reading logs afetr finalized %r' % self._name
    return self._logs

  @property
  def links(self):
    if not self._finalized:
      return self._links
    else:
      return copy.deepcopy(self._links)

  @property
  def properties(self):  # pylint: disable=E0202
    if not self._finalized:
      return self._properties
    else:
      return copy.deepcopy(self._properties)

  @properties.setter
  def properties(self, val):  # pylint: disable=E0202
    assert not self._finalized, 'Changing finalized step %r' % self._name
    assert isinstance(val, dict)
    self._properties = val

  def finalize(self, step_stream):
    self._finalized = True

    # crbug.com/833539: prune all logs from memory when finalizing.
    logs = self._logs
    self._logs = None

    if self.step_text:
      step_stream.add_step_text(self.step_text.replace('\n', '<br/>'))
    if self.step_summary_text:
      step_stream.add_step_summary_text(self.step_summary_text)
    for name, lines in logs.iteritems():
      with step_stream.new_log_stream(name) as l:
        for line in lines:
          l.write_split(line)
    for label, url in self.links.iteritems():
      step_stream.add_step_link(label, url)
    step_stream.set_step_status(self.status)
    for key, value in sorted(self._properties.iteritems()):
      step_stream.set_build_property(key, json.dumps(value, sort_keys=True))


class StepDataAttributeError(AttributeError):
  """Raised when a non-existent attributed is accessed on a StepData object."""
  def __init__(self, step, attr):
    self.step = step
    self.attr = attr
    message = ('The recipe attempted to access missing step data "%s" for step '
               '"%s". Please examine that step for errors.' % (attr, step))
    super(StepDataAttributeError, self).__init__(message)


class StepData(object):
  def __init__(self, step_config, retcode):
    self._step_config = step_config
    self._retcode = retcode

    self._presentation = StepPresentation(step_config.name)
    if step_config.ok_ret is StepConfig.ALL_OK or retcode in step_config.ok_ret:
      self._presentation.status = 'SUCCESS'
    else:
      if not step_config.infra_step:
        self._presentation.status = 'FAILURE'
      else:
        self._presentation.status = 'EXCEPTION'

    self.abort_reason = None

  @property
  def step_config(self):
    return self._step_config

  @property
  def step(self):
    """DEPRECATED: For backward compatibility only.

    Use step_config instead."""
    # TODO(iannucci): remove this
    return {
      'name': self._step_config.name,
    }

  @property
  def retcode(self):
    return self._retcode

  @property
  def presentation(self):
    return self._presentation

  def __getattr__(self, name):
    raise StepDataAttributeError(self._step_config.name, name)
