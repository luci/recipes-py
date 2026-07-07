# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Transport implementations for TurboCI Orchestrator clients."""

from __future__ import annotations

import dataclasses
import datetime
import typing

from google.protobuf import message

__all__ = [
    'TurboCITransport',
    'TurboCIAsyncTransport',
    'CallOptions',
]


@dataclasses.dataclass
class CallOptions:
  """Options to customize an individual RPC call."""

  deadline: datetime.timedelta | None = None
  metadata: typing.Mapping[str, str] = dataclasses.field(default_factory=dict)


class TurboCITransport(typing.Protocol):
  """Protocol for synchronous Turbo CI transports."""

  def call_unary(
      self,
      method_name: str,
      request: message.Message,
      options: CallOptions | None = None,
  ) -> message.Message:
    # This must raise RPCError (or subclass) on RPC errors.
    ...


class TurboCIAsyncTransport(typing.Protocol):
  """Protocol for asynchronous Turbo CI transports."""

  async def call_unary(
      self,
      method_name: str,
      request: message.Message,
      options: CallOptions | None = None,
  ) -> message.Message:
    # This must raise RPCError (or subclass) on RPC errors.
    ...
