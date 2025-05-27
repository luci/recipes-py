# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import text_format, json_format
from past.builtins import basestring

from recipe_engine.util import sentinel

# TODO(crbug.com/1147793): remove it after py3 migration is done.
def _msg_to_json_no_trailing_space(*args, **kwargs):
  jsonpb = json_format.MessageToJson(*args, **kwargs)
  return '\n'.join(l.rstrip() for l in jsonpb.splitlines())

BINARY = sentinel(
    'BINARY', ext='pb',
    enc=(lambda _self, msg, **extra: msg.SerializeToString(**extra)),
    enc_default_extra={
      'deterministic': True,
    },
    dec=(lambda _self, data, msg, **_extra: msg.ParseFromString(data)),
    dec_default_extra={})

TEXTPB = sentinel(
    'TEXTPB', ext='tpb',
    enc=staticmethod(text_format.MessageToString),
    enc_default_extra={},
    dec=staticmethod(text_format.Parse),
    dec_default_extra={})

JSONPB = sentinel(
    'JSONPB',
    ext='json',
    enc=staticmethod(_msg_to_json_no_trailing_space),
    enc_default_extra={
        'preserving_proto_field_name': True,
        'sort_keys': True,
        'indent': 2,
    },
    dec=staticmethod(json_format.Parse),
    dec_default_extra={'ignore_unknown_fields': True})


ALL_ENCODINGS = (BINARY, JSONPB, TEXTPB)
ENC_MAP = {str(enc): enc for enc in ALL_ENCODINGS}


def resolve(codec):
  """Resolves a codec to JSONPB, BINARY or TEXTPB.

  `codec` may be a string of the codec name, or the codec itself.

  Returns a codec.
  Raises a ValueError if the codec cannot be found.
  """
  if isinstance(codec, basestring):
    codec = ENC_MAP.get(codec, codec)
  if codec not in ALL_ENCODINGS: # pragma: no cover
    raise ValueError('Must specify a valid codec, got %r' % (codec,))
  return codec


def do_enc(codec, proto_msg, **extra_args):
  """Does a proto encoding operation.

  Args:
    * codec (JSONPB|BINARY|TEXTPB|str) - One of the codec
      sentinels, or its name.
    * proto_msg (message.Message) - A protobuf message to encode.
    * extra_args (dict|None) - any extra arguments for the encoder.

  Returns string of the encoded proto_msg.
  """
  codec = resolve(codec)

  extras = codec.enc_default_extra.copy()
  extras.update(extra_args)
  return codec.enc(proto_msg, **extras)

def do_dec(data, msg_class, codec, **extra_args):
  """Does a proto decoding operation.

  Args:
    * data (basestring) - The data to parse.
    * codec (JSONPB|BINARY|TEXTPB|str) - One of the codec
      sentinels, or its name.
    * proto_msg (message.Message) - A protobuf message to encode.
    * extra_args (dict|None) - any extra arguments for the encoder.

  Returns string of the encoded proto_msg.
  """
  codec = resolve(codec)

  extras = codec.dec_default_extra.copy()
  extras.update(extra_args)
  ret = msg_class()
  codec.dec(data, ret, **extras)
  return ret
