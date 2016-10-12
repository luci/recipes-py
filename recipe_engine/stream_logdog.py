# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""stream.StreamEngine implementation for LogDog, using Milo annotation
protobuf.
"""

import collections
import contextlib
import copy
import datetime
import functools
import itertools
import os
import threading
import sys

from . import env
from . import stream
from . import util

import google.protobuf.message
import google.protobuf.timestamp_pb2 as timestamp_pb2
import libs.logdog.bootstrap
import libs.logdog.stream
import libs.logdog.streamname
import annotations_pb2 as pb


# The datetime for the epoch.
_EPOCH = datetime.datetime.utcfromtimestamp(0)

# The annotation stream ContentType.
#
# This must match the ContentType for the annotation binary protobuf, which
# is specified in "<luci-go>/common/proto/milo/util.go".
ANNOTATION_CONTENT_TYPE = 'text/x-chrome-infra-annotations; version=2'


class _Environment(object):
  """Simulated system environment. The StreamEngine uses this to probe for
  system parameters. By default, the environment will be derived from the
  actual system.
  """

  def __init__(self, now_fn, argv, environ, cwd):
    self._now_fn = now_fn
    self.argv = argv
    self.environ = environ
    self.cwd = cwd

  @property
  def now(self):
    return self._now_fn()

  @classmethod
  def real(cls):
    """Returns (_Environment): An _Environment bound to the real system"""
    return cls(
        now_fn=datetime.datetime.now,
        argv=sys.argv[:],
        environ=dict(os.environ),
        cwd=os.getcwd(),
    )


class _StepStreamMeta(type):
  """Metaclass for StepStream that automatically notifies the engine of
  potential step data change if the step variable is accessed by an overridden
  (callback) method.

  The alternative to this is to hope that implementors remember to perform this
  check each time they modify the step, which could be a problem if the ABC
  methods change at some point in the future. This option concentrates all of
  the checking evil in one place.
  """

  def __new__(mcs, name, parents, attrs):
    assert len(parents) == 1

    # Wrap implemented methods so that if they modify the StepStream's embedded
    # Step, they will automatically notify the StepStream's engine.
    attrs['_step'] = property(
        mcs._wrap_set_step_referenced(attrs['_step'].fget),
        doc=attrs['_step'].__doc__)
    for k, v in attrs.iteritems():
      if k.startswith('__') or not (callable(v) and hasattr(parents[0], k)):
        continue
      attrs[k] = mcs._wrap_notify_annotation_changed(v)
    return super(_StepStreamMeta, mcs).__new__(mcs, name, parents, attrs)

  @classmethod
  def _wrap_set_step_referenced(mcs, fn):
    """Wraps the "_step" property to set a flag if referenced.

    This flag is used by functions wrapped via "_wrap_notify_annotated_changed"
    to detect if they should consider notifying the StreamEngine.
    """
    @functools.wraps(fn)
    def mark_referenced(wrapSelf, *args, **kwargs):
      wrapSelf._meta_step_referenced = True
      return fn(wrapSelf, *args, **kwargs)
    return mark_referenced

  @classmethod
  def _wrap_notify_annotation_changed(mcs, fn):
    """Wraps a function to automatically notify the StreamEngine when the Step
    changes.
    """
    @functools.wraps(fn)
    def notify_after(wrapSelf, *args, **kwargs):
      wrapSelf._meta_step_referenced = False
      try:
        return fn(wrapSelf, *args, **kwargs)
      finally:
        if wrapSelf._meta_step_referenced:
          wrapSelf._engine._notify_annotation_changed()
    return notify_after


class StreamEngine(stream.StreamEngine):
  """A stream.StreamEngine implementation that uses Logdog streams and Milo
  annotation protobufs.

  The generated LogDog streams will be (relative to "name_base"):
  /annotations
      The base annotations stream.

  /steps/<step_name>/
      Base stream name for a given step. Note that if multiple steps normalize
      to the same <step_name> value, an index will be appended, such as
      <step_name>_0. This can happen because the stream name component of a
      step is normalized, so two validly-independent steps ("My Thing" and
      "My_Thing") will both normalize to "My_Thing". In this case, the second
      one would have the stream name component, "My_Thing_1".

  /steps/<step_name>/stdout
      STDOUT stream for step "<step_name>".
  /steps/<step_name>/stderr
      STDOUT stream for step "<step_name>".

  /steps/<step_name>/logs/<log_name>/<log_name_index>
      Stream name for a given step's logs. <log_name_index> is the index of the
      log with the given normalized name. This is similar to <step_name>, only
      the index is added as a separate stream name component.
  """

  # The name of the annotation stream.
  ANNOTATION_NAME = 'annotations'

  # The default amount of time in between anotation pushes.
  DEFAULT_UPDATE_INTERVAL = datetime.timedelta(seconds=30)


  def __init__(self, client=None, streamserver_uri=None, name_base=None,
               dump_path=None, ignore_triggers=False, environment=None,
               update_interval=None):
    """Initializes a new LogDog/Annotation StreamEngine.

    Args:
      client (libs.logdog.stream.StreamClient or None): the LogDog stream client
          to use. If this is None, a new StreamClient will be instantiated when
          this StreamEngine is opened.
      streamserver_uri (str or None): The LogDog Butler stream server URI. See
          LogDog client library docs for details on supported protocols and
          format. This will only be used when "client" is None. If this is also
          None, a StreamClient will be created through probing.
      name_base (str or None): The default stream name prefix that will be added
          to generated LogDog stream names. If None, no prefix will be applied.
      dump_path (str or None): If provided, a filesystem path where the final
          recipe annotation protobuf binary will be dumped.
      ignore_triggers (bool): Triggers are not supported in LogDog annotation
          streams. If True, attempts to trigger will be silently ignored. If
          False, they will cause a NotImplementedError to be raised.
      environment (_Environment or None): The _Environment instance to use for
          operations. This will be None at production, but can be overridden
          here for testing.
      update_interval (datetime.timedelta or None): The interval of time between
          annotation data pushes. If None, DEFAULT_UPDATE_INTERVAL will be
          used.
    """

    self._client = client
    self._streamserver_uri = streamserver_uri
    self._name_base = _StreamName(name_base)
    self._dump_path = dump_path
    self._ignore_triggers = ignore_triggers
    self._env = environment or _Environment.real()
    self._update_interval = update_interval or self.DEFAULT_UPDATE_INTERVAL

    self._astate = None

    self._annotation_stream = None
    self._annotation_monitor = None
    self._streams = collections.OrderedDict()


  class TextStream(stream.StreamEngine.Stream):

    def __init__(self, fd):
      super(StreamEngine.TextStream, self).__init__()
      self._fd = fd

    ##
    # Implement stream.StreamEngine.Stream
    ##

    def write_line(self, line):
      self._fd.write(line)
      self._fd.write('\n')

    def write_split(self, string):
      self._fd.write(string)
      if not string.endswith('\n'):
        self._fd.write('\n')

    def close(self):
      self._fd.close()


  class StepStream(stream.StreamEngine.StepStream):
    """An individual step stream."""

    __metaclass__ = _StepStreamMeta

    def __init__(self, engine, step):
      """Initialize a new StepStream.

      Args:
        engine (StreamEngine): The StreamEngine that owns this StepStream.
        step (pb.Step): The Step instance that this Stream is managing.
      """
      # We will lazily create the STDOUT stream when the first data is written.
      super(StreamEngine.StepStream, self).__init__()

      self._engine = engine

      self._step_value = step
      self._step_referenced = False

      # We keep track of the log streams associated with this step.
      self._log_stream_index = {}

      # We will lazily instantiate our stdout stream when content is actually
      # written to it.
      self._stdout_stream = None

      # The retained step summary text. When generating failure details, this
      # will be consumed to populate their text field.
      self._summary_text = None

    @classmethod
    def create(cls, engine, step):
      strm = cls(engine, step)

      # Start our step.
      strm._step.msg.status = pb.RUNNING
      engine._set_timestamp(strm._step.msg.started)

      return strm

    @property
    def _step(self):
      return self._step_value

    def _get_stdout(self):
      if self._stdout_stream is None:
        # Create a new STDOUT text stream.
        stream_name = self._step.stream_name_base.append('stdout')
        self._stdout_stream = self._engine._client.open_text(str(stream_name))

        self._step.msg.stdout_stream.name = str(stream_name)
      return self._stdout_stream

    ##
    # Implement stream.StreamEngine.Stream
    ##

    def write_line(self, line):
      stdout = self._get_stdout()
      stdout.write(line)
      stdout.write('\n')

    def write_split(self, string):
      stdout = self._get_stdout()
      stdout.write(string)
      if not string.endswith('\n'):
        stdout.write('\n')

    def close(self):
      if self._stdout_stream is not None:
        self._stdout_stream.close()

      # If we still have retained summary text, a failure, and no failure detail
      # text, copy it there.
      if self._summary_text is not None:
        if (self._step.msg.HasField('failure_details') and
            not self._step.msg.failure_details.text):
          self._step.msg.failure_details.text = self._summary_text

      # Close our Step.
      self._engine._close_step(self._step.msg)

    ##
    # Implement stream.StreamEngine.StepStream
    ##

    def new_log_stream(self, log_name):
      # Generate the base normalized log stream name for this log.
      stream_name = self._step.stream_name_base.append('logs', log_name)

      # Add the log stream index to the end of the stream name.
      index = self._log_stream_index.setdefault(str(stream_name), 0)
      self._log_stream_index[str(stream_name)] = index + 1
      stream_name = stream_name.append(str(index))

      # Create a new log stream for this name.
      fd = self._engine._client.open_text(str(stream_name))

      # Update our step to include the log stream.
      link = self._step.msg.other_links.add(label=log_name)
      link.logdog_stream.name = str(stream_name)

      return self._engine.TextStream(fd)

    def add_step_text(self, text):
      self._step.msg.text.append(text)

    def add_step_summary_text(self, text):
      self._step.msg.text.insert(0, text)
      self._summary_text = text

    def add_step_link(self, name, url):
      self._step.msg.other_links.add(label=name, url=url)

    def reset_subannotation_state(self):
      pass

    def set_step_status(self, status):
      if status == 'SUCCESS':
        self._step.msg.status = pb.SUCCESS
      elif status == 'WARNING':
        self._step.msg.status = pb.SUCCESS
        self._step.msg.failure_details.type = pb.FailureDetails.GENERAL
      elif status == 'FAILURE':
        self._step.msg.status = pb.FAILURE
        self._step.msg.failure_details.type=pb.FailureDetails.GENERAL
      elif status == 'EXCEPTION':
        self._step.msg.status = pb.FAILURE
        self._step.msg.failure_details.type = pb.FailureDetails.EXCEPTION
      else:
        raise ValueError('Unknown status [%s]' % (status,))

    def set_build_property(self, key, value):
      self._engine._anno.update_properties(key=value)

    def trigger(self, trigger_spec):
      if self._engine._ignore_triggers:
        return
      raise NotImplementedError(
          'Stream-based triggering is not supported for LogDog. Please use '
          'a recipe module (e.g., buildbucket) directly for build scheduling.')


  def new_step_stream(self, step_config):
    # TODO(dnj): In the current iteration, subannotations are NOT supported.
    # In order to support them, they would have to be parsed out of the stream
    # and converted into Milo Annotation protobuf. This is a non-trivial effort
    # and may be a waste of time, as in a LogDog-enabled world, the component
    # emitting sub-annotations would actually just create its own annotation
    # stream and emit its own Milo protobuf.
    #
    # Components that emit subannotations and don't want to be converted to use
    # LogDog streams could bootstrap themselves through Annotee and let it do
    # the work.
    #
    # For now, though, we explicitly do NOT support LogDog running with
    # subannotations enabled.
    if step_config.allow_subannotations:
      raise NotImplementedError('Subannotations are not supported with LogDog '
                                'output.')

    strm = self.StepStream.create(self, self._astate.create_step(step_config))
    self._notify_annotation_changed()
    return strm

  def open(self):
    # Initialize our client, if one is not provided.
    if self._client is None:
      if self._streamserver_uri:
        self._client = libs.logdog.stream.create(self._streamserver_uri)
      else:
        # Probe the stream client via Bootstrap.
        bootstrap = libs.logdog.bootstrap.probe()
        self._client = bootstrap.stream_client()

    annotation_stream_name = self._name_base.append(self.ANNOTATION_NAME)
    self._annotation_stream = self._client.open_datagram(
        str(annotation_stream_name),
        content_type=ANNOTATION_CONTENT_TYPE)

    self._annotation_monitor = _AnnotationMonitor(
        self._env, self._annotation_stream, self._update_interval)

    # Initialize our open streams list.
    self._streams.clear()

    # Initialize our annotation state.
    self._astate = _AnnotationState.create(self._name_base,
                                           environment=self._env)
    self._astate.base.status = pb.RUNNING
    self._set_timestamp(self._astate.base.started)
    self._notify_annotation_changed()

  def close(self):
    assert self._astate is not None, 'StreamEngine is not open.'

    # Shut down any outstanding streams that may not have been closed for
    # whatever reason.
    for s in reversed(self._streams.values()):
      s.close()

    # Close out our root Step. Manually check annotation state afterwards.
    self._close_step(self._astate.base)
    self._notify_annotation_changed()

    # Shut down our annotation monitor and close our annotation stream.
    last_step_data = self._annotation_monitor.flush_and_join()
    self._annotation_stream.close()

    # Clear our client and state. We are now closed.
    self._streams.clear()
    self._client = None
    self._astate = None

    # If requested, write out the last step data.
    #
    # If there is no last step data, this will write an empty file, which is
    # still a valid protobuf.
    if self._dump_path and last_step_data:
      with open(self._dump_path, 'wb') as fd:
          fd.write(last_step_data)

  def _notify_annotation_changed(self):
    if self._astate is None:
      return

    step_data = self._astate.check()
    if step_data is not None:
      self._annotation_monitor.signal_update(step_data)

  def _set_timestamp(self, dst, dt=None):
    """Populates a timestamp_pb2.Timestamp, dst, with a datetime.

    Args:
      dst (timestamp_pb2.Timestamp): the timestamp protobuf that will be loaded
          with the time.
      dt (datetime.datetime or None): If not None, the datetime to load. If
          None, the current time (via now) will be used.
    """
    dt = (dt) if dt else (self._env.now)

    # Convert to milliseconds from epoch.
    v = (dt - _EPOCH).total_seconds()

    dst.seconds = int(v)
    dst.nanos = int((v - dst.seconds) * 1000000000.0) # Remainder as nanos.

  def _close_step(self, step):
    """Closes a step, and any open substeps, propagating status.

    If all of the substeps are already closed, this will do nothing. However, if
    any are open, it will close them with an infra failure state.

    If any substeps failed, the failure will be propagated to step.

    Args:
      step (pb.Step): The Step message to close.
    """
    # Close any open substeps, in case some of them didn't close.
    failed = []
    incomplete = []
    for sub in step.substep:
      if not sub.HasField('step'):
        # Not an embedded substep.
        continue

      # Did this step actually complete? It should have, by now, so if it didn't
      # we'll be reporting an infra failure in "step".
      if sub.step.status not in (pb.SUCCESS, pb.FAILURE):
        incomplete.append(sub.step)

      # Close this substep. This may be a no-op, if the substep is already
      # closed.
      self._close_step(sub.step)

      # If a substep failed, propagate its failure status to "step".
      if sub.step.status == pb.FAILURE:
        failed.append(sub.step)

      # If we had any incomplete steps, mark that we failed.
      if incomplete:
        step.status = pb.FAILURE
        if step.failure_details is None:
          step.failure_details = pb.FailureDetails(
              type=pb.FailureDetails.INFRA,
              text='Some substeps did not complete: %s' % (
                  ', '.join(s.name for s in incomplete)),
          )
      elif failed:
        step.status = pb.FAILURE
        if step.failure_details is None:
          # This step didn't successfully close, so propagate an infra failure.
          step.failure_details = pb.FailureDetails(
              type=pb.FailureDetails.GENERAL,
              text='Some substeps failed: %s' % (
                  ', '.join(s.name for s in failed)),
          )

    # Now close "step". If it's still RUNNING, assume that it was successful.
    if step.status == pb.RUNNING:
      step.status = pb.SUCCESS
    if not step.HasField('ended'):
      self._set_timestamp(step.ended)



class _AnnotationMonitor(object):
  """The owner of the annotation datagram stream, sending annotation updates in
  a controlled manner and buffering them when the content hasn't changed.

  By default, since annotation state can change rapidly, minor annotation
  changes are throttled such that they are only actually sent periodically.

  New annotation state updates can be installed by calling `signal_update`.
  After being started, the _AnnotationMonitor thread must be shut down by
  calling its `flush_and_join` method.
  """

  def __init__(self, env, fd, flush_period):
    self._env = env
    self._fd = fd
    self._flush_period = flush_period

    # The following group of variables is protected by "_lock".
    self._lock = threading.Lock()
    self._current_data = None
    self._flush_timer = None
    self._last_flush_time = None
    self._last_flush_data = None

  def signal_update(self, step_data, structural=False):
    """Updates the annotation state with new step data.

    This updates our state to include new step data. The annotation monitor
    will pick this up and dispatch it, either:
    - Eventually, when the flush period completes, or
    - Immediately, if this is a structural change.

    TODO(dnj): Re-examine the use case for "structural" based on actual usage
    and decide to remove / use it.

    Args:
      step_data (str): The updated binary annotation protobuf step data.
      structural (bool): If True, this is a structural update and should be
          pushed immediately.
    """
    with self._lock:
      # Did our data actually change?
      if step_data == self._last_flush_data:
        # Nope, leave things as-is.
        return

      # This is new data. Is it structural? If so, flush immediately.
      # If not, make sure our timer is running so it will eventually be flushed.
      # Note that the timer may also suggest that we flush immediately if we're
      # already past our last flush interval.
      now = self._env.now
      self._current_data = step_data
      if structural or self._set_flush_timer_locked(now):
        # We should flush immediately.
        self._flush_now_locked(now)

  def flush_and_join(self):
    """Flushes any remaining updates and blocks until the monitor is complete.

    Returns (pb.Step): The final Step protobuf, or None if no step data was
        sent.
    """
    # Mark that we're finished and signal our event.
    with self._lock:
      self._flush_now_locked(self._env.now)
      return self._last_flush_data

  @property
  def latest(self):
    with self._lock:
      return self._last_flush_data

  def _flush_now_locked(self, now):
    # Clear any current flush timer.
    self._clear_flush_timer_locked()

    # Record this flush.
    #
    # We set the last flush time to now because even if we don't actually send
    # data, we have responded to the flush request.
    flush_data, self._current_data = self._current_data, None
    self._last_flush_time = now

    # If the data hasn't changed since the last flush, then don't actually
    # do anything.
    if flush_data is None or flush_data == self._last_flush_data:
      return

    self._last_flush_data = flush_data
    self._fd.send(flush_data)

  def _clear_flush_timer_locked(self):
    if self._flush_timer is not None:
      self._flush_timer.cancel()
      self._flush_timer = None

  def _set_flush_timer_locked(self, now):
    if self._flush_timer is not None:
      # Our flush timer is already running.
      return False

    if self._last_flush_time is None:
      # We have never flushed before, so flush immediately.
      return True

    deadline = self._last_flush_time + self._flush_period
    if deadline <= now:
      # We're past our flush deadline, and should flush immediately.
      return True

    # Start our flush timer.
    self._flush_timer = threading.Timer((deadline - now).total_seconds(),
                                        self._flush_timer_expired)
    self._flush_timer.daemon = True
    self._flush_timer.start()

  def _flush_timer_expired(self):
    with self._lock:
      self._flush_now_locked(self._env.now)


class _AnnotationState(object):
  """Manages an outer Milo annotation protobuf Step."""

  Step = collections.namedtuple('Step', (
      'msg', 'stream_name_base', 'substream_name_index'))

  def __init__(self, base_step, stream_name_base):
    self._base = self.Step(
        msg=base_step,
        stream_name_base=stream_name_base,
        substream_name_index={})
    self._check_snapshot = None

    # The current step stack. This is built by updating state after new steps'
    # nesting levels.
    self._nest_stack = [self._base]

    # Index initial properties.
    self._properties = {p.name: p for p in self._base.msg.property}

  @classmethod
  def create(cls, stream_name_base, environment=None, properties=None):
    base = pb.Step()
    base.name = 'steps'
    base.status = pb.PENDING
    if environment:
      if environment.argv:
        base.command.command_line.extend(environment.argv)
      if environment.cwd:
        base.command.cwd = environment.cwd
      if environment.environ:
        base.command.environ.update(environment.environ)
    if properties:
      for k, v in sorted(properties.iteritems()):
        base.property.add(name=k, value=v)
    return cls(base, stream_name_base)

  @property
  def base(self):
    return self._base.msg

  def check(self):
    """Checks if the annotation state has been updated and, if so, returns it.

    After check returns, the latest annotation state will be used as the current
    snapshot for future checks.

    Returns (str/None): A serialized binary Step protobuf if modified, None
        otherwise.
    """
    if self._check_snapshot is None or self._check_snapshot != self.base:
      self._check_snapshot = copy.deepcopy(self.base)
      return self._check_snapshot.SerializeToString()
    return None

  def create_step(self, step_config):
    # Identify our parent Step by examining the nesting level. The first step
    # in the nest stack will always be the base (nesting level "-1", since it's
    # the parent of level 0). Since the step's "nest_level" is one more than the
    # parent, and we need to offset by 1 to reach the stack index, they cancel
    # each other out, so the nest level is the same as the parent's stack index.
    assert step_config.nest_level < len(self._nest_stack), (
        'Invalid nest level %d (highest is %d)' % (
            step_config.nest_level, len(self._nest_stack)-1))

    # Clear any items in the nest stack that are deeper than the current
    # element.
    del(self._nest_stack[step_config.nest_level+1:])
    parent = self._nest_stack[-1]

    # Create a stream name for this step. Even though step names are unique,
    # the normalized LogDog step name may overlap with a different step name.
    # We keep track of the step names we've issued to this step space and
    # add indexes if a conflict is identified.
    stream_name_base = parent.stream_name_base.append('steps',
                                                      step_config.base_name)
    index = parent.substream_name_index.setdefault(str(stream_name_base), 0)
    parent.substream_name_index[str(stream_name_base)] += 1
    if index > 0:
      stream_name_base += '_%d' % (index,)

    # Create and populate our new step.
    msg = parent.msg.substep.add().step
    msg.name = step_config.base_name
    msg.status = pb.PENDING
    if step_config.cmd:
      msg.command.command_line.extend(step_config.cmd)
    if step_config.cwd:
      msg.command.cwd = step_config.cwd
    if step_config.env:
      msg.command.environ = step_config.env

    step = self.Step(
        msg=msg,
        stream_name_base=stream_name_base,
        substream_name_index={})
    self._nest_stack.append(step)
    return step

  def update_properties(self, **kwargs):
    """Updates a Step's property values to incorporate kwargs."""
    for k, v in sorted(kwargs.iteritems()):
      cur = self._properties.get(k)
      if cur is None:
        cur = self.base.property.add(name=k, value=str(v))
        self._properties[k] = cur
        continue

      # A Property message already exists for this key, so update its value.
      if cur.value != v:
        cur.value = str(v)


class _StreamName(object):
  """An immutable validated wrapper for a LogDog stream name."""

  def __init__(self, base):
    if base is not None:
      libs.logdog.streamname.validate_stream_name(base)
    self._base = base

  def append(self, *components):
    """Returns (_StreamName): A new _StreamName instance with components added.

    Each component in "components" will become a new normalized stream name
    component. Conseqeuntly, any separators (/) in the components will be
    replaced with underscores.

    Args:
      components: the path components to append to this _StreamName.
    """
    if len(components) == 0:
      return self

    components = [self._normalize(self._flatten(p))
                  for p in reversed(components)]
    if self._base:
      components.append(self._base)
    return type(self)('/'.join(reversed(components)))

  def augment(self, val):
    """Returns (_StreamName): A new _StreamName with "val" appended.

    This generates a new, normalized _StreamName with the contents of "val"
    appended to the end. For example:

    Original:         "foo/bar"
    Append "baz qux": "foo/barbaz_qux"
    """
    if not val:
      return self
    val = self._flatten(val)
    if self._base:
      val = self._base + val
    return type(self)(self._normalize(val))

  def __iadd__(self, val):
    return self.augment(val)

  @staticmethod
  def _flatten(v):
    return v.replace('/', '_')

  @staticmethod
  def _normalize(v):
    return libs.logdog.streamname.normalize(v, prefix='s_')

  def __str__(self):
    if not self._base:
      raise ValueError('Cannot generate string from empty StreamName.')
    return self._base
