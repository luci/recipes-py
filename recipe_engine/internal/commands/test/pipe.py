# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Support methods to help read+write protobuf messages from a pipe (aka pair of
file descriptors)."""

import struct
import os


def read_message(in_file, msg_class):
  """Reads the given proto Message subclass from the file descriptor `in_file`.

  This expects a 4-byte network-order (big-endian) size prefix, followed by
  exactly that many bytes, which should be the binary encoded form of a
  `msg_class` message.

  Args:

    * in_file (file-like object) - The handle to read the size header and proto.
    * msg_class (google.protobuf.Message subclass) - The generated proto Message
      to decode from the stream.

  Returns an instance of msg_class.
  Raises EOFError on EOF/partial read from in_file
  Raises any error that msg_class.ParseFromString could raise.
  """
  def _read(size):
    """Reads size bytes from in_file.

    If in_file is buffered, it will keep reading until there is either no data
      left, or it has read size bytes.

    Raises:
      EOFError: EOF/partial read from in_file
    """
    data = in_file.read(size)
    while len(data) < size:
      new_data = in_file.read(size-len(data))
      if not new_data:
        break
      data += new_data

    if data is None or len(data) != size:
      raise EOFError('reached EOF and did not get all data requested')

    return data

  raw_size = _read(4)

  size, = struct.unpack('!L', raw_size)
  if size == 0:
    return None

  data = _read(size)

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
