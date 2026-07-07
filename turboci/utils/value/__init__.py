# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helpers for manipulating TurboCI Value{Write,Ref,Data} protos."""

from google.protobuf import message as _message

# Re-export all symbols from sub-modules.

# The standard type url prefix used by any_pb2.Any.
TYPE_URL_PREFIX = 'type.googleapis.com/'


# We define `url` here because it's used by many of our contained modules.
def url(msg: _message.Message | type[_message.Message]) -> str:
  """Helper to get the type_url from a proto message.

  Useful for tests.

  Args:
    msg: The proto message type or instance.

  Returns:
    The type_url used by any_pb2.Any (e.g. type.googleapis.com/...)
  """
  return f'{TYPE_URL_PREFIX}{msg.DESCRIPTOR.full_name}'


# go/keep-sorted start
from turboci.utils.value.absorb import *
from turboci.utils.value.data_source import *
from turboci.utils.value.decode import *
from turboci.utils.value.digest import *
from turboci.utils.value.iter import *
from turboci.utils.value.match import *
from turboci.utils.value.ordered import *
from turboci.utils.value.refs_writes import *
from turboci.utils.value.type_filter import *
# go/keep-sorted end
