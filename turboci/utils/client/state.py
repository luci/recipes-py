# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helper to keep track of state needed for TurboCI client interactions."""

from __future__ import annotations

import copy
import dataclasses
import logging
import typing

from google.protobuf import message
from google.protobuf import timestamp_pb2
from PB.turboci.graph.ids.v1 import identifier as identifier_pb2
from PB.turboci.graph.orchestrator.v1 import allocate_worknode_ids_request as allocate_worknode_ids_request_pb2
from PB.turboci.graph.orchestrator.v1 import cancel_workplan_request as cancel_workplan_request_pb2
from PB.turboci.graph.orchestrator.v1 import query_nodes_request as query_nodes_request_pb2
from PB.turboci.graph.orchestrator.v1 import query_nodes_response as query_nodes_response_pb2
from PB.turboci.graph.orchestrator.v1 import read_workplan_request as read_workplan_request_pb2
from PB.turboci.graph.orchestrator.v1 import read_workplan_response as read_workplan_response_pb2
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_request as write_nodes_request_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_response as write_nodes_response_pb2
from turboci.utils import value
from turboci.utils.client import retry

__all__ = [
    'Logger',
    'State',
]


# These req types need to have their `token` field populated for outgoing
# requests.
_NEEDS_TOKEN_INJECTION = (
    allocate_worknode_ids_request_pb2.AllocateWorkNodeIDsRequest,
    cancel_workplan_request_pb2.CancelWorkPlanRequest,
    query_nodes_request_pb2.QueryNodesRequest,
    read_workplan_request_pb2.ReadWorkPlanRequest,
    write_nodes_request_pb2.WriteNodesRequest,
)

# These rsp types have `value_data` which should be interned into our
# cache.
_HAS_VALUE_DATA = (
    read_workplan_response_pb2.ReadWorkPlanResponse,
    query_nodes_response_pb2.QueryNodesResponse,
)


class Logger(typing.Protocol):
  """Protocol defining the logging interface by this package.

  Some downstream users of this package will need to supply a not-quite
  logging.Logger.
  """

  def debug(self, msg: str, *args: typing.Any, **kwargs: typing.Any) -> None:
    ...

  def info(self, msg: str, *args: typing.Any, **kwargs: typing.Any) -> None:
    ...

  def warning(self, msg: str, *args: typing.Any, **kwargs: typing.Any) -> None:
    ...

  def error(self, msg: str, *args: typing.Any, **kwargs: typing.Any) -> None:
    ...

  def exception(
      self, msg: str, *args: typing.Any, **kwargs: typing.Any
  ) -> None:
    ...


class NullLock:
  """A no-op context manager for async uses of State."""

  def __enter__(self) -> None:
    pass

  def __exit__(self, exc_type, exc_val, exc_tb) -> None:
    _ = (exc_type, exc_val, exc_tb)


_LockT = typing.TypeVar('_LockT', bound=typing.ContextManager[typing.Any])


@dataclasses.dataclass(kw_only=True)
class State(typing.Generic[_LockT]):
  # (required) The workplan this client is bound to.
  wpid: identifier_pb2.WorkPlan

  # Logger instance for client operations and debugging.
  logger: Logger = dataclasses.field(
      default_factory=lambda: logging.getLogger('turboci.client')
  )

  # The token to inject into outgoing responses.
  #
  # The token will be provided as part of an executor RunStageRequest, or as
  # part of a CreateWorkPlanResponse.
  #
  # Leaving this empty will cause this client to be considered 'external' to
  # all WorkPlans, which requires a different set of permissions vs. clients
  # bound to a particular WorkPlan.
  token: str | None = None

  # Default TypeInfo for this client.
  #
  # Added to all outgoing read requests which do not explicitly set TypeInfo.
  default_known_types: None | value.TypeInfo = None

  # The maintained MutableDataSource.
  #
  # This defaults to a LockedDataSource, but if you know this state will only
  # be used from a single thread, use SimpleDataSource instead.
  data: value.MutableDataSource = dataclasses.field(
      default_factory=value.LockedDataSource
  )

  # Retry policy.
  retry_policy: retry.Retry = dataclasses.field(default_factory=retry.Retry)

  # WARNING: Callbacks are executed while holding the state lock (_state_mu).
  # Callbacks MUST NOT interact with the client or State directly (e.g.
  # accessing properties or registering callbacks) and MUST be quick and
  # non-blocking to avoid deadlocks.
  _on_state_change: set[
      typing.Callable[[stage_pb2.StageAttemptCurrentState], None]
  ] = dataclasses.field(default_factory=set, init=False)

  # The latest observed stage attempt state.
  # Protected by _state_mu. Read via the latest_attempt_state property.
  _latest_attempt_state: stage_pb2.StageAttemptCurrentState = dataclasses.field(
      default_factory=stage_pb2.StageAttemptCurrentState, init=False
  )

  # Mutex protecting latest_attempt_state and on_state_change.
  #
  # Subclasses will populate this from __post_init__.
  _state_mu: _LockT = dataclasses.field(
      default_factory=NullLock, init=False  # type: ignore[assignment]
  )

  @property
  def latest_attempt_state(self) -> stage_pb2.StageAttemptCurrentState:
    """Returns the latest observed stage attempt state (thread-safe)."""
    with self._state_mu:
      return self._latest_attempt_state

  @staticmethod
  def ts_as_float(ts: None | timestamp_pb2.Timestamp) -> float:
    """Renders a Timestamp to a python float timestamp.

    Previously this used AsDatetime, however this doesn't set a default timezone
    in the returned datetime, leading to bugs :(.

    As a convenience, if this is given None, it returns negative infinity (which
    will sort before all other values, except for negative infinity).
    """
    if not ts:
      return float('-inf')
    return ts.seconds + (ts.nanos / 1e9)

  def register_on_state_change(
      self, fn: typing.Callable[[stage_pb2.StageAttemptCurrentState], None]
  ):
    """Call `fn` when we observe a newer version of the current attempt state.

    This can happen after any WriteNodes call.

    The function will be called while holding the state lock (_state_mu).
    It MUST NOT interact with the client or State directly (e.g., accessing
    properties like latest_attempt_state or registering/unregistering
    callbacks) and must be quick and non-blocking to avoid deadlocks.

    Only works for States bound to a Stage Attempt (e.g. for a Stage Executor
    within the context of running some Stage).

    If this State has already observed some StageAttemptCurrentState, `fn` will
    be called immediately with this value before this function returns.
    """
    with self._state_mu:
      self._on_state_change.add(fn)
      if self._latest_attempt_state.HasField('version'):
        try:
          fn(self._latest_attempt_state)
        except Exception:
          self.logger.exception('While processing current state change.')

  def unregister_on_state_change(
      self, fn: typing.Callable[[stage_pb2.StageAttemptCurrentState], None]
  ):
    """Unregisters a function previously used with `register_on_state_change`.

    No-op if the function was not registered, or if called multiple times for
    the same function.
    """
    with self._state_mu:
      self._on_state_change.discard(fn)

  def _adjust_request(self, req: message.Message) -> None:
    """Hook to adjust the req before sending (e.g., injecting tokens).

    This is done by finding all methods on `self` (possibly from subclasses)
    which start with "_adjust_request_".
    """
    for name in dir(self):
      if name.startswith('_adjust_request_'):
        getattr(self, name)(req)

  def _adjust_request_token(self, req: message.Message) -> None:
    if self.token and isinstance(req, _NEEDS_TOKEN_INJECTION):
      req.token = self.token

  def _adjust_request_known_types(self, req: message.Message) -> None:
    if self.default_known_types:
      match req:
        case read_workplan_request_pb2.ReadWorkPlanRequest():
          if not req.value_filter.HasField('type_info'):
            req.value_filter.type_info.CopyFrom(
                self.default_known_types.to_proto()
            )

        case query_nodes_request_pb2.QueryNodesRequest():
          if not req.HasField('type_info'):
            req.type_info.CopyFrom(self.default_known_types.to_proto())

  def _process_response(
      self, req: message.Message, rsp: message.Message
  ) -> None:
    """Hook to observe the rsp after a successful RPC.

    This is done by finding all methods on `self` (possibly from subclasses)
    which start with "_process_response_".
    """
    for name in dir(self):
      if name.startswith('_process_response_'):
        getattr(self, name)(req, rsp)

  def _process_response_value_data(
      self, req: message.Message, rsp: message.Message
  ) -> None:
    _ = req
    if isinstance(rsp, _HAS_VALUE_DATA):
      self.data.update(rsp.value_data)

  def _process_response_current_attempt_state(
      self, req: message.Message, rsp: message.Message
  ) -> None:
    _ = req
    if isinstance(rsp, write_nodes_response_pb2.WriteNodesResponse):
      if rsp.HasField('current_attempt_state'):
        new_state = copy.deepcopy(rsp.current_attempt_state)
        with self._state_mu:
          new_ver = self.ts_as_float(new_state.version.ts)
          old_ver = self.ts_as_float(
              self._latest_attempt_state.version.ts
              if self._latest_attempt_state
              else None
          )

          if new_ver > old_ver:
            self._latest_attempt_state = new_state
            for cb in list(self._on_state_change):
              try:
                cb(new_state)
              except Exception:
                self.logger.exception('While processing current state change.')
