# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines helpers for creating ValueRef and ValueWrite messages."""

from __future__ import annotations

__all__ = [
    'ref',
    'ref_from_write',
    'write',
]

import typing

from google.protobuf import message
from google.protobuf import any_pb2

from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb2
from PB.turboci.graph.orchestrator.v1 import value_write as value_write_pb2
from PB.turboci.graph.orchestrator.v1 import omit_reason as omit_reason_pb2
from turboci.utils.value import digest


def write(
    data: message.Message,
    realm: (
        typing.Literal[
            '',
            '$from_container',
            '$from_token',
        ]
        | str
    ) = '$from_container',
) -> value_write_pb2.ValueWrite:
  """Makes a ValueWrite.

  The special realm forms have the following meanings:
    * '' - This value must already exist in the DB. For example, if you are
      updating an existing Check Option, you can use this to indicate that
      the value must already exist, and write permission in this existing
      realm will be used.
    * '$from_token' - This will use the realm encoded in the token you provide
      with the WriteNodes RPC call. If the token is from WorkPlan creation,
      the realm is the realm of the WorkPlan. If the token is from Stage
      execution (that is; you are calling as part of a Stage Attempt), then the
      realm is that of the Stage you are running as.
    * '$from_container' - This will use the realm of the containing object.
      Stages and Checks are contained in their WorkPlan. Values (options,
      results, attempt details, etc.) are contained in their respective Stage
      or Check.

  Args:
    data: Proto message to store. As a convenience, if this is literally
      any_pb2.Any, it's used verbatim.
    realm: The security realm for this ref, or one of the special realm forms.
      Defaults to '$from_container'.

  Returns:
    A ValueWrite with data set to the Any-packed version of `data`.
  """
  apb: any_pb2.Any
  if isinstance(data, any_pb2.Any):
    apb = data
  else:
    apb = any_pb2.Any()
    apb.Pack(data, deterministic=True)
  return value_write_pb2.ValueWrite(data=apb, realm=realm)


def ref(
    data: message.Message,
    realm: str,
    *,
    omit_reason: (
        typing.Literal[
            'OMIT_REASON_UNWANTED',
            'OMIT_REASON_NO_ACCESS',
            'OMIT_REASON_MISSING',
        ]
        | None
        | omit_reason_pb2.OmitReason
    ) = None,
) -> value_ref_pb2.ValueRef:
  """Makes an inline ValueRef.

  Useful for testing.

  Args:
    data: Proto message to store `inline`.
    realm: The security realm for this ref.
    omit_reason: An optional omit_reason to set on the returned ref.

  Returns:
    A ValueRef with inline set to the Any-packed version of `data`.

  Raises:
    ValueError if realm is a special realm form (empty, $from_token, etc.).
  """
  return ref_from_write(write(data, realm), omit_reason=omit_reason)


def ref_from_write(
    val_write: value_write_pb2.ValueWrite,
    *,
    omit_reason: (
        typing.Literal[
            'OMIT_REASON_UNWANTED',
            'OMIT_REASON_NO_ACCESS',
            'OMIT_REASON_MISSING',
        ]
        | None
        | omit_reason_pb2.OmitReason
    ) = None,
) -> value_ref_pb2.ValueRef:
  """Returns a ValueRef (with inline data) for a ValueWrite.

  Useful for testing.

  Args:
    val_write: The ValueWrite to convert.
    omit_reason: An optional omit_reason to set on the returned ref.

  Returns:
    A ValueRef populated from `val_write`

  Raises:
    ValueError if realm is a special realm form (empty, $from_token, etc.).
  """
  if val_write.realm in ('', '$from_container', '$from_token'):
    raise ValueError(f'invalid realm for ValueRef: {val_write.realm!r}')

  return value_ref_pb2.ValueRef(
      type_url=val_write.data.type_url,
      inline=val_write.data,
      digest=str(digest.Digest.compute(val_write.data)),
      realm=val_write.realm,
      omit_reason=omit_reason,
  )
