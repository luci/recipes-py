# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""gRPC transport implementations for TurboCI Orchestrator clients."""

from __future__ import annotations

from google.protobuf import message
from google.rpc import status_pb2
import grpc
from grpc_status import rpc_status
from turboci.utils import client
from turboci.utils.client import errors

__all__ = [
    'GrpcTransport',
    'GrpcAsyncTransport',
]


def _translate_grpc_error(err: grpc.RpcError) -> Exception:
  """Translates a grpc.RpcError into an RPCError.

  Extracts rich error details (StageAttemptCurrentState) if present.
  """
  # grpc.RpcError also implements grpc.Call
  if not isinstance(err, grpc.Call):
    return err

  status = rpc_status.from_call(err)
  if status is None:
    code_val = err.code().value
    code = code_val[0] if isinstance(code_val, tuple) else code_val
    status = status_pb2.Status(code=code, message=err.details())

  return errors.MakeRPCError(
      message=status.message,
      status=status,
  )


class GrpcTransport:
  """Synchronous gRPC transport."""

  def __init__(self, stub):
    self.stub = stub

  def call_unary(
      self,
      method_name: str,
      request: message.Message,
      options: client.CallOptions | None = None,
  ) -> message.Message:
    method = getattr(self.stub, method_name)
    metadata = list(options.metadata.items()) if options else None
    timeout = (
        options.deadline.total_seconds()
        if options and options.deadline
        else None
    )
    try:
      return method(request, timeout=timeout, metadata=metadata)
    except grpc.RpcError as err:
      raise _translate_grpc_error(err) from err


class GrpcAsyncTransport:
  """Asynchronous gRPC transport."""

  def __init__(self, stub):
    self.stub = stub

  async def call_unary(
      self,
      method_name: str,
      request: message.Message,
      options: client.CallOptions | None = None,
  ) -> message.Message:
    method = getattr(self.stub, method_name)
    metadata = list(options.metadata.items()) if options else None
    timeout = (
        options.deadline.total_seconds()
        if options and options.deadline
        else None
    )
    try:
      # In grpc.aio, unary calls are awaitable
      return await method(request, timeout=timeout, metadata=metadata)
    except grpc.RpcError as err:
      raise _translate_grpc_error(err) from err
