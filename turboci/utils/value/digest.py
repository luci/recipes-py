# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Contains symbols to manipulate TurboCI Digests.

Includes the derministic serialization of Any messages.
"""

from __future__ import annotations

__all__ = [
    'Digest',
    'deterministially_serialize_any',
]

import base64
import hashlib
import io
import struct
import typing

from google.protobuf import any_pb2
from google.protobuf import message
from google.protobuf.internal import encoder
from google.protobuf.internal import wire_format

from PB.turboci.graph.orchestrator.v1 import value_digest as value_digest_pb2


def _varint_encoder():
  """Return an encoder for a basic varint value (does not include tag)."""
  # Copied from google.protobuf.internal rather than import the mangled
  # symbol. Modified to remove unused parameter from the returned function.

  local_int2byte = struct.Struct('>B').pack

  def encode_varint(write, value):
    bits = value & 0x7F
    value >>= 7
    while value:
      write(local_int2byte(0x80 | bits))
      bits = value & 0x7F
      value >>= 7
    return write(local_int2byte(bits))

  return encode_varint


_encode_varint = _varint_encoder()


def _varint_decoder():
  """Return an encoder for a basic varint value (does not include tag).

  Decoded values will be bitwise-anded with the given mask before being
  returned, e.g. to limit them to 32 bits.  The returned decoder does not
  take the usual "end" parameter -- the caller is expected to do bounds
  checking after the fact (often the caller can defer such checking until
  later).  The decoder returns a (value, new_pos) pair.
  """

  # Copied from google.protobuf.internal rather than import the mangled
  # symbol.
  # Removes mask and type-generic construction to just use 64 bit mask and
  # `int`.
  # Switches to `DecodeError` instead of the underscored flavor.
  # Switches to `while True` to help type checkers realize the loop never
  # terminates except via return.

  def decode_varint(buffer: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
      b = buffer[pos]
      result |= (b & 0x7F) << shift
      pos += 1
      if not b & 0x80:
        result &= (1 << 64) - 1
        result = int(result)
        return (result, pos)
      shift += 7
      if shift >= 64:
        raise message.DecodeError('Too many bytes when decoding varint.')

  return decode_varint


_decode_varint = _varint_decoder()

_sha256_size = hashlib.sha256().digest_size


class Digest(str):
  """Digest is the string form of the digest in a ValueRef.

  This can be constructed directly by casting a ValueRef.digest to this type,
  or via computation from an Any using `Digest.compute()`.

  Digests can be decoded to their proto ValueDigest form for inspection of
  the raw data hash, hash type and size of the original data.
  """

  @staticmethod
  def compute(data: any_pb2.Any) -> Digest:
    """Calculates a Digest from `data`."""

    h = hashlib.sha256(usedforsecurity=False)
    data_len = _size_any(data)
    _write_any_bytes(data, h.update)
    dgst = h.digest()
    buf = io.BytesIO()
    buf.truncate(len(dgst) + wire_format.Int32ByteSizeNoTag(data_len) + 1)
    buf.write(dgst)
    _encode_varint(buf.write, data_len)
    buf.write(value_digest_pb2.VALUE_HASH_ALGO_SHA256.to_bytes(1, 'big'))
    ret = base64.urlsafe_b64encode(buf.getbuffer()).rstrip(b'=')
    return Digest(ret.decode())

  def to_proto(self) -> value_digest_pb2.ValueDigest:
    """Decodes a Digest to its ValueDigest form.

    Returns:
      The decoded ValueDigest proto.

    Raises:
      ValueError if the Digest is malformed.
    """

    # We add == to the end which is the maximum amount of possibly missing
    # padding; urlsafe_b64decode will ignore the extra.
    dat = base64.urlsafe_b64decode(str(self) + '==')
    if not dat:
      raise ValueError('missing algorithm')
    if dat[-1] != value_digest_pb2.VALUE_HASH_ALGO_SHA256:
      raise ValueError(f'bad algorithm: 0x{dat[-1]!r}')
    dat = dat[:-1]
    dgst = dat[:_sha256_size]
    if len(dgst) != _sha256_size:
      raise ValueError('insufficient bytes for hash')
    size, pos = _decode_varint(dat, _sha256_size)
    if pos != len(dat):
      raise ValueError('extra bytes while decoding size')
    return value_digest_pb2.ValueDigest(
        algo='VALUE_HASH_ALGO_SHA256', size_bytes=size, hash=dgst
    )


_WriterFunc = typing.Callable[[bytes], None]
_Encoder = typing.Callable[[_WriterFunc, bytes | str, bool], None]

_any_type_url_encoder = typing.cast(
    _Encoder, encoder.StringEncoder(1, False, False)
)
_any_type_url_sizer = typing.cast(
    typing.Callable[[str], int], encoder.StringSizer(1, False, False)
)
_any_value_tag_encoder = typing.cast(
    _Encoder, encoder.BytesEncoder(2, False, False)
)
_any_value_sizer = typing.cast(
    typing.Callable[[bytes], int], encoder.BytesSizer(2, False, False)
)


def _size_any(data: any_pb2.Any) -> int:
  ret = 0
  if type_url := data.type_url:
    ret += _any_type_url_sizer(type_url)
  if value := data.value:
    ret += _any_value_sizer(value)
  return ret


def _write_any_bytes(data: any_pb2.Any, w: typing.Any):
  """Write the bytes for an Any to the given writer function.

  Args:
    data: The Any message to write.
    w: The writer function to write to (callable taking Buffer as first
      argument). This is hard to make a proper type annotation for in 3.11.
  """
  if type_url := data.type_url:
    _any_type_url_encoder(w, type_url, True)
  if value := data.value:
    _any_value_tag_encoder(w, value, True)


def deterministially_serialize_any(data: any_pb2.Any) -> bytes:
  """Deterministic and error-free function to serialize an Any."""
  buf = io.BytesIO()
  buf.truncate(_size_any(data))
  _write_any_bytes(data, buf.write)
  return buf.getvalue()
