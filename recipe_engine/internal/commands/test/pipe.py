# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Support methods to help read+write protobuf messages from a pipe (aka pair of
file descriptors)."""

import struct


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
