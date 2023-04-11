# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import copy
import json
import operator

try:
  from collections import UserList
except ImportError:
  # TODO: python2 import
  from UserList import UserList

from functools import reduce

from builtins import str as text
from future.utils import iteritems

import attr
from gevent.local import local
from google.protobuf import json_format as json_pb
from google.protobuf import message

from .internal.attr_util import attr_type


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
    return FrozenDict((freeze(k), freeze(v)) for k, v in iteritems(obj))
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
    return {k: thaw(v) for k, v in iteritems(obj)}
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
                        (hash(i) for i in enumerate(iteritems(self._d))), 0)

  def __eq__(self, other):
    if not isinstance(other, collections.Mapping):
      return NotImplemented
    if self is other:
      return True
    if len(self) != len(other):
      return False
    for k, v in iteritems(self):
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
    return 'FrozenDict(%r)' % (list(iteritems(self._d)),)


def _fix_stringlike(value):
  """_fix_stringlike will decode `bytes` with backslashreplace and return
  the decoded value.

  If `value` is a text or str, returns it unchanged.

  Otherwise rases ValueError.
  """
  if isinstance(value, (text, str)):
    return value

  if isinstance(value, bytes):
    return value.decode('utf-8', errors='backslashreplace')

  raise ValueError(
      "Expected object of (str, bytes) but got %s" % (type(value),))


class _StringSequence(UserList):
  # NOTE: it could potentially be more efficient to implement the __add__ family
  # of operators to avoid re-fix_stringlike'ing `items` here, but not worth the
  # implementation complexity.
  def __init__(self, initlist=None):
    super(_StringSequence, self).__init__()
    if initlist is not None:
      self.data = [_fix_stringlike(i) for i in initlist]

  def __iadd__(self, other):
    """__iadd__ is called for `_StringSequence() += ...`

    We want to make sure `other` is properly fixed first.
    """
    if isinstance(other, _StringSequence):
      # other.data is already validated (unless the user is doing something
      # REALLY weird).
      self.data.extend(other.data)
    else:
      self.extend(other)
    return self

  def __setitem__(self, i, item):
    self.data[i] = _fix_stringlike(item)

  def __setslice__(self, i, j, other):
    i = max(i, 0)
    j = max(j, 0)
    if isinstance(other, _StringSequence):
      self.data[i:j] = other.data
    else:
      self.data[i:j] = [_fix_stringlike(i) for i in other]

  def append(self, item):
    self.data.append(_fix_stringlike(item))

  def insert(self, i, item):
    self.data.insert(i, _fix_stringlike(item))

  def extend(self, other):
    self.data.extend(_fix_stringlike(l) for l in other)


class _OrderedDictString(collections.OrderedDict):
  """_OrderedDictString implements some sort of constraints on the insane
  StepPresentation.logs type.

  In particular, it attempts to make sure that the value of entries in this dict
  are either common_pb2.Log, str, or _StringSequence, without exception.

  _StringSequence, in turn, emulates a strict list(str) type, converting bytes
  to str with _fix_stringlike.
  """

  def __setitem__(self, key, value):
    # late proto import
    from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
    if isinstance(value, (common_pb2.Log, text, str, _StringSequence)):
      # these values are fine
      pass
    elif isinstance(value, bytes):
      value = _fix_stringlike(value)
    elif isinstance(value, collections.Iterable):
      value = _StringSequence(value)
    else:
      raise ValueError(
          "Attempted to assign non-(bytes/str or sequence(bytes/str)) "
          "data as log value: %r" % (type(value),)
      )

    return super(_OrderedDictString, self).__setitem__(key, value)

  def setdefault(self, key, default):
    if key in self:
      return self[key]
    self[key] = default
    return self[key]  # __setitem__ can replace a list with a _StringSequence.


class StepPresentation(object):
  """StepPresentation allows recipes to alter the presentation of their recipe
  step in both the Buildbucket Build message, as well as it's visual
  presentation on e.g. ci.chromium.org (i.e. 'milo' UI service).

  You can obtain a StepPresentation object after running as step like:

     result = api.step(step_name, ['program', ...])
     presentation = result.presentation  # StepPresentation

  Your code has read/write access to the properties of this StepPresentation
  until it is `finalized`. Finalization happens when either the next step in the
  same greenlet (aka "Future") is started, or when the current greenlet or 'nest
  step' (i.e. `with api.step.nest(...):`) exits.

  The following step properties are available:

  # logs
  Logs are line-based text (utf-8) data. Steps, by default, have a `stdout` log
  which contains the combined stdout+stderr of the subprocess run in the step.
  Steps which use `stdout=(...)` or `stderr=(...)` will not see this information
  present on the step (that is: the recipe engine does not `tee` these outputs,
  just redirects them to the placeholder files).

  Logs is a map of `log name` (str) to `log data`. Log data can be a str, bytes,
  or a list of str or bytes. If given in list form, the items in the list are
  treated as lines separated by "\n". So, `'hello\nworld'` and
  `['hello', 'world']` are identical log data.

  If log data is bytes (or a list containing bytes entries), the bytes entries
  will be formatted as utf-8 using `errors='backslashreplace'`. We use
  backslashreplace as the most useful scheme. It will not let the reader
  distinguish between '\x1b' and r'\x1b', but typically this is the output from
  e.g. test commands where it is possible to distinguish based on context.

  If users want to use a different utf-8 encoding of the raw data, they
  can do so in their recipe.

  # status
  Status represents the overall status of this step, which directly impacts how
  it is rendered on the UI. For legacy reasons, there is currently a mismatch
  between the values of `status` and the values that Buildbucket uses in the
  Build message.

  The mapping is (status value, Buildbucket enum, default UI color):
    * 'SUCCESS'    SUCCESS        green
    * 'WARNING'    SUCCESS        green   # see crbug.com/854099
    * 'FAILURE'    FAILURE        red
    * 'EXCEPTION'  INFRA_FAILURE  purple
    * 'CANCELED'   CANCELED       blue

  NOTE: 'WARNING' is a valid value, but does not do anything differently than
  'SUCCESS'. The best way to implement warnings, currently, is to use
  `step_text` or `step_summary_text` to describe what is wrong.

  # had_timeout
  If True, indicates that this step timed out in some way.
  Has no functional effect on the presentation of the step, but can be used by
  your recipe code to see if the step ended due to a timeout.

  # was_cancelled
  If True, indicates that this step was canceled (i.e. an external non-timeout
  event happened which caused the recipe engine to terminate the step). This can
  happen when your recipe code explicitly uses the `Future.cancel()` function
  from the `futures` module, or if an external process sent the recipe engine
  SIGTERM/CTRL-BREAK while the step was running.

  # properties
  Properties are a way to export structured data from the OVERALL recipe. For
  very legacy reasons, these are attached to StepPresentation, rather than
  having a singular API for the overall exported data. See crbug.com/1409983.

  Recipes stream their output properties; Buildbucket users who observe the
  Build will see properties show up on the overall Build roughly as soon as the
  StepPresentation finalizes.

  Property keys here correspond to the TOP LEVEL output property key of the
  whole Build. If multiple steps emit the same output property key, only the
  lastmost step (i.e. the step which was finalized last) will have its value
  preserved. There is no merging or combining of values.

  For example:

      api.step('one', ...).presentation.properties['propname'] = [1000]
      api.step('two', ...).presentation.properties['propname'] = ["hi"]

  An observer of this build would see the Build output properties look like:

      {"propname": [1000]}  # after `one` finalized
      {"propname": ["hi"]}  # after `two` finalized

  Effectively, output properties are "write only". This was a (likely
  misguided) attempt to prevent recipes from using output properties as a way to
  pass state in-between otherwise unrelated pieces of code as a sort of global
  variable.

  # tags
  Tags are arbitrary key/value string pairs which can be set that will apply to
  THIS step only, are rendered in the UI, and are also exported via the
  Buildbucket API. They are intended as a way for EngProd teams to annotate
  individual steps with stable identifiers and/or to report a bit more
  information about this specific step, without needing to resort to parsing the
  summary_markdown field.

  Tag keys should indicate the domain or system which interprets them. For
  example:

     my_service.category    = "COMPILE" - good
     other_service.critical = "1"       - good

     important = "1"                    - bad; important to who/what system?
     is_compile = "yes"                 - bad; what will interpret this?
                                        - should other recipes copy this key?

  The "luci." prefix is reserved for LUCI's own use.
  The key and value must be utf-8 and not exceed 256/1024 bytes each.
  Neither key nor value can be empty.

  # step_summary_text, step_text and links
  These three properties are combined to populate the `summary_markdown` field
  of the Buildbucket Step.

  `step_summary_text` and `step_text` are used, verbatim, as the first and/or
  second paragraphs of the markdown.

  Links are a simple mapping of link name to a URL. This implementation will
  replace spaces in links with '%20', but does no other URL processing. Links
  are added to the `summary_markdown` by turning them into the final paragraph
  as a bullet list.
  """


  _RAW_STATUSES = (
    None, 'SUCCESS', 'WARNING', 'FAILURE', 'EXCEPTION', 'CANCELED')
  STATUSES = frozenset(status for status in _RAW_STATUSES if status)

  # TODO(iannucci): use attr for this

  @classmethod
  def status_worst(cls, status_a, status_b):
    """Given two STATUS strings, return the worse of the two."""
    if not hasattr(cls, 'STATUS_TO_BADNESS'):
      cls.STATUS_TO_BADNESS = freeze({
        status: i for i, status in enumerate(StepPresentation._RAW_STATUSES)})

    if cls.STATUS_TO_BADNESS[status_a] > cls.STATUS_TO_BADNESS[status_b]:
      return status_a
    return status_b

  def __init__(self, step_name):
    self._name = step_name
    self._finalized = False

    self._logs = _OrderedDictString()
    self._links = collections.OrderedDict()
    self._status = None
    self._had_timeout = False
    self._was_cancelled = False
    self._step_summary_text = ''
    self._step_text = ''
    self._properties = {}
    self._tags = {}

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
  def was_cancelled(self):
    return self._was_cancelled

  @was_cancelled.setter
  def was_cancelled(self, val):
    assert not self._finalized, 'Changing finalized step %r' % self._name
    assert isinstance(val, bool)
    self._was_cancelled = val

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

  @property
  def tags(self):
    if not self._finalized:
      return self._tags
    else:
      return copy.deepcopy(self._tags)

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
    # late proto import
    from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
    for name, log in iteritems(logs):
      if isinstance(log, common_pb2.Log):
        step_stream.append_log(log)
      else:
        with step_stream.new_log_stream(name) as log_stream:
          if isinstance(log, (text, str, bytes)):
            self.write_data(log_stream, log)
          elif isinstance(log, collections.Iterable):
            for line in log:
              self.write_data(log_stream, line)
          else:
            raise ValueError('log %r has unknown log type %s: %r' %
                             (name, type(log), log))
    for label, url in iteritems(self._links):
      # We fix spaces in urls; It's an extremely common mistake to make, and
      # easy to remedy here.
      #
      # TODO(iannucci) - This seems simultaneously beneficial (?) and woefully
      # insufficient.
      step_stream.add_step_link(text(label), text(url).replace(" ", "%20"))
    for key, value in sorted(iteritems(self._properties)):
      if isinstance(value, message.Message):
        value = json_pb.MessageToDict(value)
      step_stream.set_build_property(key, json.dumps(value, sort_keys=True))
    for key, value in sorted(iteritems(self._tags)):
      step_stream.set_step_tag(key, value)
    step_stream.set_step_status(self.status, self.had_timeout)

  @staticmethod
  def write_data(log_stream, data):
    """Write the supplied data into the logstream.

    Args:
      log_stream (stream.StreamEngine.Stream) - The target log stream. In
        production, this is backed by a text log stream created by logdog
        butler.
      data (Union[str, bytes]) - Data to write. If the supplied data is bytes,
        it should be valid utf-8 encoded bytes. Note that, in py2 mode, the
        supported types are unicode and str respectively. However, due to
        historical reason, data is str in py2 that doesn't have valid utf-8
        encoding is accepted but discouraged.
    """
    if isinstance(data, text):
      # unicode in py2 and str in py3
      log_stream.write_split(data)
    elif isinstance(data, str):  # str in py2
      # TODO(yiwzhang): try decode and warn user if non-valid utf-8
      # encoded data is supplied because log_stream only supports valid utf-8
      # text in python3.
      log_stream.write_split(data)
    elif isinstance(data, bytes):  #  bytes in py3
      # We assume data is valid utf-8 encoded bytes here after transition to
      # python3. If there's a need to write raw bytes, we should support binary
      # log stream here.
      log_stream.write_split(data.decode('utf-8'))
    else:
      raise ValueError('unknown data type %s: %r' % (type(data), data))


@attr.s(frozen=True)
class ResourceCost(object):
  """A structure defining the resources that a given step may need.

  For use with `api.step`; attaching a ResourceCost to a step will allow the
  recipe engine to prevent too many costly steps from running concurrently.

  See `api.step.ResourceCost` for full documentation.
  """
  cpu = attr.ib(validator=attr_type(int), default=500)
  memory = attr.ib(validator=attr_type(int), default=50)
  disk = attr.ib(validator=attr_type(int), default=0)
  net = attr.ib(validator=attr_type(int), default=0)

  @classmethod
  def zero(cls):
    """Returns a ResourceCost with zero for all resources."""
    return cls(0, 0, 0, 0)

  def __attrs_post_init__(self):
    if self.cpu < 0:
      raise ValueError('negative cpu amount')
    if self.memory < 0:
      raise ValueError('negative memory amount')
    if self.disk < 0 or self.disk > 100:
      raise ValueError('disk not in [0,100]')
    if self.net < 0 or self.net > 100:
      raise ValueError('net not in [0,100]')

  def __nonzero__(self):
    return not self.fits(0, 0, 0, 0)

  def __str__(self):
    bits = []
    if self.cpu > 0:
      cores = ('%0.2f' % (self.cpu / 1000.)).rstrip('0').rstrip('.')
      bits.append('cpu=[%s cores]' % (cores,))
    if self.memory > 0:
      bits.append('memory=[%d MiB]' % (self.memory,))
    if self.disk > 0:
      bits.append('disk=[%d%%]' % (self.disk,))
    if self.net > 0:
      bits.append('net=[%d%%]' % (self.net,))
    return ', '.join(bits)

  def fits(self, cpu, memory, disk, net):
    """Returns True if this Resources fits within the given constraints."""
    return (
      self.cpu <= cpu and
      self.memory <= memory and
      self.disk <= disk and
      self.net <= net
    )


# A (global) registry of all PerGreentletState objects.
#
# This is used by the recipe engine to call back each
# PerGreenletState._get_setter_on_spawn when the recipe spawns a new greenlet
# (via the "recipe_engine/futures" module).
#
# Reset in between test runs by the simulator.
class _PerGreentletStateRegistry(list):
  def clear(self):
    """Clears the Registry."""
    self[:] = []

PerGreentletStateRegistry = _PerGreentletStateRegistry()

class PerGreenletState(local):
  """Subclass from PerGreenletState to get an object whose state is tied to the
  current greenlet.

    from recipe_engine.engine_types import PerGreenletState

    class MyState(PerGreenletState):
      cool_stuff = True
      neat_thing = ""

      def _get_setter_on_spawn(self):
        # called on greenlet spawn; return a closure to propagate values from
        # the previous greenlet to the new greenlet.
        old_cool_stuff = self.cool_stuff
        def _inner():
          self.cool_stuff = old_cool_stuff
        return _inner

    class MyApi(RecipeApi):
      def __init__(self):
        self._state = MyState()

      @property
      def cool(self):
        return self._state.cool_stuff

      @property
      def neat(self):
        return self._state.neat_thing

      def calculate(self):
        self._state.cool_stuff = False
        self._state.neat_thing = "yes"
  """

  def __new__(cls, *args, **kwargs):
    ret = super(PerGreenletState, cls).__new__(cls, *args, **kwargs)
    PerGreentletStateRegistry.append(ret)
    return ret

  def _get_setter_on_spawn(self):
    """This method should be overridden by your subclass. It will be invoked by
    the engine immediately BEFORE spawning a new greenlet, and it should return
    a 0-argument function which should repopulate `self` immediately AFTER
    spawning the new greenlet.

    Example, a PerGreenletState which simply copies its old state to the new
    state:

      def _get_setter_on_spawn(self):
        pre_spawn_state = self.state
        def _inner():
          self.state = pre_spawn_state
        return _inner

    This will allow reads and sets of the PerGreenletState's fields to be
    per-greenlet, but carry across from greenlet to greenlet.

    If this function is not implemented, or returns None, the PerGreenletState
    contents will be reset in the new greenlet.
    """
    pass
