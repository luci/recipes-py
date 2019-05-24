# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Support methods to help read+write protobuf messages from a pipe (aka pair of
file descriptors)."""

import struct
import threading

import attr


def read_message(in_file, msg_class):
  """Reads the given proto Message subclass from the file descriptor `in_file`.

  This expects a 4-byte network-order (big-endian) size prefix, followed by
  exactly that many bytes, which should be the binary encoded form of a
  `msg_class` message.

  Args:

    * in_file (file-like object) - The handle to read the size header and proto.
    * msg_class (google.protobuf.Message subclass) - The generated proto Message
      to decode from the stream.

  Returns None (on EOF/partial read) or an instance of msg_class.
  Raises any error that msg_class.ParseFromString could raise.
  """
  raw_size = in_file.read(4)
  if raw_size is None or len(raw_size) != 4:
    return None

  size, = struct.unpack('!L', raw_size)
  data = in_file.read(size)
  if data is None or len(data) != size:
    return None

  ret = msg_class()
  ret.ParseFromString(data)
  return ret


def write_message(out_file, message):
  """Serializes `message` to binary proto, writes a size header and the proto
  data to `out_file`.

  Args:

    * out_file (writeable file-like object) - The handle to write the header and
      proto to.
    * message (instance of google.protobuf.Message subclass) - The message to
      write.

  Returns True iff both writes succeeded.
  Raises anything message.SerializeToString could raise.
  """
  out_data = message.SerializeToString()
  try:
    out_file.write(struct.pack('!L', len(out_data)))
    out_file.write(out_data)
    return True
  except IOError:
    return False


@attr.s
class Channel(object):
  """A crappy implementation of a synchronized channel of unbounded size.

  The Channel should be initialized with the number of writers (e.g.
  `Channel(8)`). Each writer must call dec_writer exactly once, or readers of
  the Channel will block indefinitely. By default there's one writer per
  Channel.

  To be replaced with `gevent.Channel` asap.
  """
  _writers = attr.ib(default=1)

  _data = attr.ib(init=False, factory=list)
  _crash_message = attr.ib(init=False, default=None)
  _cond = attr.ib(init=False, factory=threading.Condition)

  _living_writers = attr.ib(init=False)
  @_living_writers.default
  def _living_writers_default(self):
    return self._writers

  class EmergencyTeardown(Exception):
    """Raised from .get() when the Channel is in the 'crashed' state."""

  def get(self):
    """Returns the next item in the Channel.

    If the Channel is 'crashed', raises EmergencyTeardown.
    if the Channel has no more writers and no items, returns None.

    Blocks until an item is available, the channel crashes, or runs out of
    writers+items.
    """
    with self._cond:
      while True:
        if self._crash_message:
          self._cond.notify_all()
          raise self.EmergencyTeardown(self._crash_message)

        if self._data:
          return self._data.pop()

        if self._living_writers <= 0:
          self._cond.notify_all()
          return None

        self._cond.wait()

  def put(self, data):
    """Adds an item to the Channel.

    Channel must not be closed. Will raise an AssertionError if this is the
    case.

    If the channel is crashed, this ignores the put.
    """
    with self._cond:
      assert self._living_writers, 'Channel has no living writers?'
      if not self._crash_message:
        self._data.append(data)
        self._cond.notify()

  def dec_writer(self):
    """Decrements the number of living writers by one.

    Must be called exactly once per writing entity (i.e. the number that you
    pass to the Channel constructor).

    When all the writers have called this once, threads blocking in .get() will
    be woken up (i.e. the Channel is closed).
    """
    with self._cond:
      self._living_writers -= 1
      if self._living_writers == 0:
        self._cond.notify_all()
      assert self._living_writers >= 0, 'Decremented living writers below 0.'

  def crash(self, message):
    """Used for shutting down the Channel immediately; consumers blocking on get
    will have EmergencyTeardown raised, even if there are items left in the
    Channel.

    If the channel is already crashed, raises an AssertionError.

    Args:

      * message (str) - The message for the EmergencyTeardown exception.
    """
    with self._cond:
      assert not self._crash_message, (
        'Cannot crash twice. Tried to set crash with %r which would '
        'overwrite the current crash message %r.'
      ) % (message, self._crash_message)
      self._crash_message = message
      self._cond.notify_all()
