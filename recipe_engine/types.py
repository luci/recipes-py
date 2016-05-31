# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import copy
import json
import operator


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


class FrozenDict(collections.Mapping):
  """An immutable OrderedDict.

  Modified From: http://stackoverflow.com/a/2704866
  """
  def __init__(self, *args, **kwargs):
    self._d = collections.OrderedDict(*args, **kwargs)

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
    return self._d[key]

  def __hash__(self):
    return self._hash

  def __repr__(self):
    return 'FrozenDict(%r)' % (self._d.items(),)


class StepPresentation(object):
  STATUSES = set(('SUCCESS', 'FAILURE', 'WARNING', 'EXCEPTION'))

  def __init__(self):
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
    assert not self._finalized
    assert val in self.STATUSES
    self._status = val

  @property
  def step_text(self):
    return self._step_text

  @step_text.setter
  def step_text(self, val):
    assert not self._finalized
    self._step_text = val

  @property
  def step_summary_text(self):
    return self._step_summary_text

  @step_summary_text.setter
  def step_summary_text(self, val):
    assert not self._finalized
    self._step_summary_text = val

  @property
  def logs(self):
    if not self._finalized:
      return self._logs
    else:
      return copy.deepcopy(self._logs)

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
    assert not self._finalized
    assert isinstance(val, dict)
    self._properties = val

  def finalize(self, step_stream):
    self._finalized = True
    if self.step_text:
      step_stream.add_step_text(self.step_text)
    if self.step_summary_text:
      step_stream.add_step_summary_text(self.step_summary_text)
    for name, lines in self.logs.iteritems():
      with step_stream.new_log_stream(name) as l:
        for line in lines:
          l.write_split(line)
    for label, url in self.links.iteritems():
      step_stream.add_step_link(label, url)
    step_stream.set_step_status(self.status)
    for key, value in self._properties.iteritems():
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
  def __init__(self, step, retcode):
    self._retcode = retcode
    self._step = step

    self._presentation = StepPresentation()
    self.abort_reason = None

  @property
  def step(self):
    return copy.deepcopy(self._step)

  @property
  def retcode(self):
    return self._retcode

  @property
  def presentation(self):
    return self._presentation

  def __getattr__(self, name):
    raise StepDataAttributeError(self._step['name'], name)
