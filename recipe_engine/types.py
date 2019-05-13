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
  RAW_STATUSES = ('SUCCESS', 'WARNING', 'FAILURE', 'EXCEPTION')
  STATUSES = frozenset(RAW_STATUSES)

  # TODO(iannucci): use attr for this

  @classmethod
  def status_worst(cls, status_a, status_b):
    """Given two STATUS strings, return the worse of the two."""
    if not hasattr(cls, 'STATUS_TO_BADNESS'):
      cls.STATUS_TO_BADNESS = freeze({
        status: i for i, status in enumerate(StepPresentation.RAW_STATUSES)})

    if cls.STATUS_TO_BADNESS[status_a] > cls.STATUS_TO_BADNESS[status_b]:
      return status_a
    return status_b

  def __init__(self, step_name):
    self._name = step_name
    self._finalized = False

    self._logs = collections.OrderedDict()
    self._links = collections.OrderedDict()
    self._status = None
    self._had_timeout = False
    self._step_summary_text = ''
    self._step_text = ''
    self._properties = {}

  @property
  def status(self):
    return self._status

  @status.setter
  def status(self, val):
    assert not self._finalized, 'Changing finalized step %r' % self._name
    assert val in self.STATUSES
    self._status = val

  def set_worse_status(self, status):
    """Sets .status to this value if it's worse than the current status."""
    self.status = self.status_worst(self.status, status)

  @property
  def had_timeout(self):
    return self._had_timeout

  @had_timeout.setter
  def had_timeout(self, val):
    assert not self._finalized, 'Changing finalized step %r' % self._name
    assert isinstance(val, bool)
    self._had_timeout = val

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
    assert not self._finalized, 'Reading logs after finalized %r' % self._name
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
      with step_stream.new_log_stream(name) as log:
        for line in lines:
          log.write_split(line)
    for label, url in self.links.iteritems():
      step_stream.add_step_link(label, url)
    for key, value in sorted(self._properties.iteritems()):
      step_stream.set_build_property(key, json.dumps(value, sort_keys=True))
    step_stream.set_step_status(self.status, self.had_timeout)
