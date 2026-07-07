# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Client implementations for TurboCI Orchestrator."""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
import typing

from google.protobuf import message
from PB.turboci.graph.orchestrator.v1 import allocate_worknode_ids_request as allocate_worknode_ids_request_pb2
from PB.turboci.graph.orchestrator.v1 import allocate_worknode_ids_response as allocate_worknode_ids_response_pb2
from PB.turboci.graph.orchestrator.v1 import cancel_workplan_request as cancel_workplan_request_pb2
from PB.turboci.graph.orchestrator.v1 import cancel_workplan_response as cancel_workplan_response_pb2
from PB.turboci.graph.orchestrator.v1 import create_workplan_request as create_workplan_request_pb2
from PB.turboci.graph.orchestrator.v1 import create_workplan_response as create_workplan_response_pb2
from PB.turboci.graph.orchestrator.v1 import query_nodes_request as query_nodes_request_pb2
from PB.turboci.graph.orchestrator.v1 import query_nodes_response as query_nodes_response_pb2
from PB.turboci.graph.orchestrator.v1 import read_workplan_request as read_workplan_request_pb2
from PB.turboci.graph.orchestrator.v1 import read_workplan_response as read_workplan_response_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_request as write_nodes_request_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_response as write_nodes_response_pb2
from turboci.utils.client import errors
from turboci.utils.client import state
from turboci.utils.client import transports

__all__ = [
    'Sync',
    'Async',
]


@dataclasses.dataclass(kw_only=True)
class Sync(state.State[threading.Lock]):
  """Stateful, non-transactional synchronous client for TurboCI Orchestrator.

  This client internally handles retries for RetryableRPCError
  exceptions (and raises all others).
  """

  # (required) The transport to the actual service.
  transport: transports.TurboCITransport

  def __post_init__(self):
    # pylint: disable=attribute-defined-outside-init
    self._state_mu = threading.Lock()

  def _execute(
      self,
      method_name: str,
      req: message.Message,
      options: transports.CallOptions | None = None,
  ) -> message.Message:
    self._adjust_request(req)
    for attempt, next_sleep_time in enumerate(self.retry_policy.attempts()):
      try:
        rsp = self.transport.call_unary(method_name, req, options)
        self._process_response(req, rsp)
        return rsp
      except errors.RetryableRPCError as e:
        if next_sleep_time is None:
          raise
        self.logger.warning(
            'Transient error in RPC %s, retrying (attempt %d) in %.2fs: %s',
            method_name,
            attempt + 1,
            next_sleep_time,
            e,
        )
        time.sleep(next_sleep_time)
    raise Exception('impossible')

  def CreateWorkPlan(
      self,
      req: create_workplan_request_pb2.CreateWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> create_workplan_response_pb2.CreateWorkPlanResponse:
    return typing.cast(
        create_workplan_response_pb2.CreateWorkPlanResponse,
        self._execute('CreateWorkPlan', req, options),
    )

  def ReadWorkPlan(
      self,
      req: read_workplan_request_pb2.ReadWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> read_workplan_response_pb2.ReadWorkPlanResponse:
    return typing.cast(
        read_workplan_response_pb2.ReadWorkPlanResponse,
        self._execute('ReadWorkPlan', req, options),
    )

  def WriteNodes(
      self,
      req: write_nodes_request_pb2.WriteNodesRequest,
      options: transports.CallOptions | None = None,
  ) -> write_nodes_response_pb2.WriteNodesResponse:
    return typing.cast(
        write_nodes_response_pb2.WriteNodesResponse,
        self._execute('WriteNodes', req, options),
    )

  def QueryNodes(
      self,
      req: query_nodes_request_pb2.QueryNodesRequest,
      options: transports.CallOptions | None = None,
  ) -> query_nodes_response_pb2.QueryNodesResponse:
    return typing.cast(
        query_nodes_response_pb2.QueryNodesResponse,
        self._execute('QueryNodes', req, options),
    )

  def AllocateWorkNodeIDs(
      self,
      req: allocate_worknode_ids_request_pb2.AllocateWorkNodeIDsRequest,
      options: transports.CallOptions | None = None,
  ) -> allocate_worknode_ids_response_pb2.AllocateWorkNodeIDsResponse:
    return typing.cast(
        allocate_worknode_ids_response_pb2.AllocateWorkNodeIDsResponse,
        self._execute('AllocateWorkNodeIDs', req, options),
    )

  def CancelWorkPlan(
      self,
      req: cancel_workplan_request_pb2.CancelWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> cancel_workplan_response_pb2.CancelWorkPlanResponse:
    return typing.cast(
        cancel_workplan_response_pb2.CancelWorkPlanResponse,
        self._execute('CancelWorkPlan', req, options),
    )


@dataclasses.dataclass(kw_only=True)
class Async(state.State[state.NullLock]):
  """Stateful, non-transactional asynchronous client for TurboCI Orchestrator.

  This client internally handles retries for RetryableRPCError
  exceptions (and raises all others).
  """

  # (required) The transport to the actual service.
  transport: transports.TurboCIAsyncTransport

  async def _execute(
      self,
      method_name: str,
      req: message.Message,
      options: transports.CallOptions | None = None,
  ) -> message.Message:
    self._adjust_request(req)
    for attempt, next_sleep_time in enumerate(self.retry_policy.attempts()):
      try:
        rsp = await self.transport.call_unary(method_name, req, options)
        self._process_response(req, rsp)
        return rsp
      except errors.RetryableRPCError as e:
        if next_sleep_time is None:
          raise
        self.logger.warning(
            'Transient error in RPC %s, retrying (attempt %d) in %.2fs: %s',
            method_name,
            attempt + 1,
            next_sleep_time,
            e,
        )
        await asyncio.sleep(next_sleep_time)
    raise Exception('impossible')

  async def CreateWorkPlan(
      self,
      req: create_workplan_request_pb2.CreateWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> create_workplan_response_pb2.CreateWorkPlanResponse:
    return typing.cast(
        create_workplan_response_pb2.CreateWorkPlanResponse,
        await self._execute('CreateWorkPlan', req, options),
    )

  async def ReadWorkPlan(
      self,
      req: read_workplan_request_pb2.ReadWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> read_workplan_response_pb2.ReadWorkPlanResponse:
    return typing.cast(
        read_workplan_response_pb2.ReadWorkPlanResponse,
        await self._execute('ReadWorkPlan', req, options),
    )

  async def WriteNodes(
      self,
      req: write_nodes_request_pb2.WriteNodesRequest,
      options: transports.CallOptions | None = None,
  ) -> write_nodes_response_pb2.WriteNodesResponse:
    return typing.cast(
        write_nodes_response_pb2.WriteNodesResponse,
        await self._execute('WriteNodes', req, options),
    )

  async def QueryNodes(
      self,
      req: query_nodes_request_pb2.QueryNodesRequest,
      options: transports.CallOptions | None = None,
  ) -> query_nodes_response_pb2.QueryNodesResponse:
    return typing.cast(
        query_nodes_response_pb2.QueryNodesResponse,
        await self._execute('QueryNodes', req, options),
    )

  async def AllocateWorkNodeIDs(
      self,
      req: allocate_worknode_ids_request_pb2.AllocateWorkNodeIDsRequest,
      options: transports.CallOptions | None = None,
  ) -> allocate_worknode_ids_response_pb2.AllocateWorkNodeIDsResponse:
    return typing.cast(
        allocate_worknode_ids_response_pb2.AllocateWorkNodeIDsResponse,
        await self._execute('AllocateWorkNodeIDs', req, options),
    )

  async def CancelWorkPlan(
      self,
      req: cancel_workplan_request_pb2.CancelWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> cancel_workplan_response_pb2.CancelWorkPlanResponse:
    return typing.cast(
        cancel_workplan_response_pb2.CancelWorkPlanResponse,
        await self._execute('CancelWorkPlan', req, options),
    )
