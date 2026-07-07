# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Helpers for heartbeating Stage Attempts."""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import datetime
import itertools
import random
import socket
import threading
import time
import typing

from PB.turboci.graph.orchestrator.v1 import stage_attempt_execution_policy as stage_attempt_execution_policy_pb2
from PB.turboci.graph.orchestrator.v1 import stage_attempt_state as stage_attempt_state_pb2
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb2
from PB.turboci.graph.orchestrator.v1 import value_write as value_write_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_request as write_nodes_request_pb2
from turboci.utils.client import clients
from turboci.utils.client import errors
from turboci.utils.client import state
from turboci.utils.client import transports

__all__ = [
    "HeartbeatOptions",
    "async_execute_stage",
    "execute_stage",
]


_EventT = typing.TypeVar("_EventT", threading.Event, asyncio.Event)
_ClientT = typing.TypeVar("_ClientT", clients.Sync, clients.Async)

# Map of stage type_url to its respective counter.
_counters = collections.defaultdict(lambda: itertools.count(1))

# Mutex protecting the _counters map.
_counters_mu = threading.Lock()


def _make_process_uid(stage: stage_pb2.Stage) -> str:
  with _counters_mu:
    count = next(_counters[stage.args.type_url])

  # Don't need to put the stage type_url in the process_uid - it's implied by
  # the current stage.
  return f"{socket.gethostname()}-{threading.get_native_id()}-{count}"


@dataclasses.dataclass
class HeartbeatOptions:
  """Options for the heartbeat of the lifecycle managers."""

  # Minimum delay (in seconds) between heartbeats to prevent tight loops /
  # orchestrator spam.
  min_delay_sec: float = 1.0

  # Minimum safety buffer (in seconds) to maintain before the heartbeat
  # deadline.
  min_buffer_sec: float = 5.0

  # Random ratio (0.0 to 1.0) of the intended delay to to subtract to give
  # a bit of fuzz.
  random_factor: float = 0.1

  # Number of write latencies to keep in the moving average.
  latency_window_size: int = 10

  # Maximum time (in seconds) to wait for the background thread/task to exit
  # during context exit.
  exit_timeout_sec: float = 5.0

  # Timeout (in seconds) for individual heartbeat/ping RPC calls.
  ping_timeout_sec: float = 5.0

  # Maximum consecutive unretriably errors before stopping the heartbeat loop
  # and shutting down.
  max_consecutive_unexpected_errors: int = 3

  # Whether to automatically transition the attempt to COMPLETE on clean exit
  # or INCOMPLETE on exception exit (if not already COMPLETE/INCOMPLETE).
  transition_on_exit: bool = True

  # History of recent write latencies (in seconds) for moving average
  # calculation.
  _latencies: list[float] = dataclasses.field(default_factory=list, init=False)

  # Counter of consecutive unexpected errors.
  consecutive_unexpected_errors: int = dataclasses.field(default=0, init=False)

  def record_latency(self, latency: float):
    """Records the latency of a SUCCESSFUL ping RPC.

    This includes any retries done by the underlying client.
    """
    self._latencies.append(latency)
    if len(self._latencies) > self.latency_window_size:
      self._latencies.pop(0)

  @property
  def average_latency(self) -> float:
    """Computes the average latency of a ping.

    Computes this across the last `latency_window_size` recorded latencies.
    """
    if not self._latencies:
      return 0.0
    return sum(self._latencies) / len(self._latencies)

  def calculate_delay(
      self, attempt_state: stage_pb2.StageAttemptCurrentState | None
  ) -> float | None:
    """Calculates the next heartbeat delay.

    Returns None if heartbeats are disabled.
    """
    if not attempt_state or not attempt_state.HasField("heartbeat_by"):
      return None

    # Figure out the absolute latest we could heartbeat.
    nominal_delay = (
        state.State.ts_as_float(attempt_state.heartbeat_by) - time.time()
    )

    # Now give ourselves some margin before that.
    nominal_delay -= max(self.min_buffer_sec, self.average_latency * 2)

    # Remove a bit of fuzz.
    if self.random_factor > 0:
      nominal_delay -= random.uniform(0, nominal_delay * self.random_factor)

    # Now cap at our minimum delay.
    return max(self.min_delay_sec, nominal_delay)


def _make_transition_request(
    transition_to: int,
    process_uid: str,
    attempt_execution_policy: (
        stage_attempt_execution_policy_pb2.StageAttemptExecutionPolicy | None
    ) = None,
) -> write_nodes_request_pb2.WriteNodesRequest:
  """Makes a request message for transitioning to SCHEDULED or RUNNING."""
  req = write_nodes_request_pb2.WriteNodesRequest()
  if transition_to == stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_SCHEDULED:
    req.reason.message = "scheduling attempt"
    scheduled = req.current_attempt.state_transition.scheduled
    scheduled.SetInParent()
    if attempt_execution_policy:
      scheduled.attempt_execution_policy.CopyFrom(attempt_execution_policy)
  elif transition_to == stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_RUNNING:
    req.reason.message = "starting attempt"
    running = req.current_attempt.state_transition.running
    running.process_uid = process_uid
    if attempt_execution_policy:
      running.attempt_execution_policy.CopyFrom(attempt_execution_policy)
  else:
    raise ValueError(f"Unsupported transition target state: {transition_to}")
  return req


def _make_heartbeat_request() -> write_nodes_request_pb2.WriteNodesRequest:
  """Makes a simple heartbeat request message for the current state."""
  req = write_nodes_request_pb2.WriteNodesRequest()
  req.reason.message = "heartbeat"
  req.current_attempt.SetInParent()
  return req


def _make_tearing_down_request(
    cancelled: bool,
    reason: str | None = None,
    details: typing.Sequence[value_write_pb2.ValueWrite] | None = None,
) -> write_nodes_request_pb2.WriteNodesRequest:
  """Makes a request message to enter the TEARING_DOWN state."""
  req = write_nodes_request_pb2.WriteNodesRequest()
  if reason is not None:
    req.reason.message = reason
  elif cancelled:
    req.reason.message = "tearing_down[cancelled]"
  else:
    req.reason.message = "tearing_down"

  if details:
    req.reason.details.extend(details)

  req.current_attempt.state_transition.tearing_down.SetInParent()
  return req


def execute_stage(
    client: clients.Sync,
    stage: stage_pb2.Stage,
    *,
    transition_to: int = stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_RUNNING,
    opts: HeartbeatOptions | None = None,
    attempt_execution_policy: (
        None | stage_attempt_execution_policy_pb2.StageAttemptExecutionPolicy
    ) = None,
) -> AttemptLifecycleManager:
  """Transitions the current stage attempt to SCHEDULED or RUNNING.

  Returns an attempt lifecycle manager which can be used as a context manager
  to surround the stage attempt implementation.

  If `opts.transition_on_exit` is True (the default), when exiting the `with`:
  - If exiting with an exception, it will attempt to transition the current
    Attempt to INCOMPLETE (unless already COMPLETE or INCOMPLETE).
  - If exiting cleanly with no exception, it will attempt to transition the
    current Attempt to COMPLETE (unless already COMPLETE or INCOMPLETE).

  Example:
    def RunStage(
      self, req: run_stage_pb2.RunStageRequest, context
    ) -> run_stage_pb2.RunStageResponse:
      lcm = execute_stage(client=self.client, stage=req.stage, opts=opts)

      def background_worker(lcm):
        with lcm:
          try:
            # Do work, routinely checking lcm.is_cancelled or calling
            lcm.assert_running()
          finally:
            lcm.start_tearing_down()
            # Perform cleanup and transition attempt to final state...

      threading.Thread(
        target=background_worker, args=(lcm,), daemon=True
      ).start()
      return run_stage_pb2.RunStageResponse()
  """
  if not opts:
    opts = HeartbeatOptions()
  process_uid = _make_process_uid(stage)
  client.WriteNodes(
      _make_transition_request(
          transition_to, process_uid, attempt_execution_policy
      ),
      options=transports.CallOptions(
          deadline=datetime.timedelta(seconds=opts.ping_timeout_sec)
      ),
  )
  return AttemptLifecycleManager(
      client=client, opts=opts, process_uid=process_uid
  )


async def async_execute_stage(
    client: clients.Async,
    stage: stage_pb2.Stage,
    *,
    transition_to: int = stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_RUNNING,
    opts: HeartbeatOptions | None = None,
    attempt_execution_policy: (
        None | stage_attempt_execution_policy_pb2.StageAttemptExecutionPolicy
    ) = None,
) -> AttemptLifecycleManagerAsync:
  """Transitions the current stage attempt to SCHEDULED or RUNNING.

  Returns an attempt lifecycle manager which can be used as a context manager
  to surround the stage attempt implementation.

  If `opts.transition_on_exit` is True (the default), when exiting the `async
  with`:
  - If exiting with an exception, it will attempt to transition the current
    Attempt to INCOMPLETE (unless already COMPLETE or INCOMPLETE).
  - If exiting cleanly with no exception, it will attempt to transition the
    current Attempt to COMPLETE (unless already COMPLETE or INCOMPLETE).

  Example:
    async def RunStage(
      self, req: run_stage_pb2.RunStageRequest, context
    ) -> run_stage_pb2.RunStageResponse:
      lcm = await async_execute_stage(client=self.client,
      stage=req.stage, opts=opts)

      async def background_worker(lcm):
        async with lcm:
          try:
            # Do work, routinely checking lcm.is_cancelled or calling
            lcm.assert_running()
          finally:
            await lcm.start_tearing_down()
            # Perform cleanup and transition attempt to final state...

      # NOTE: You will have to ensure this task gets associated with some
      # appropriate asyncio reactor loop.
      asyncio.create_task(background_worker(lcm))
      return run_stage_pb2.RunStageResponse()
  """
  if not opts:
    opts = HeartbeatOptions()
  process_uid = _make_process_uid(stage)
  await client.WriteNodes(
      _make_transition_request(
          transition_to, process_uid, attempt_execution_policy
      ),
      options=transports.CallOptions(
          deadline=datetime.timedelta(seconds=opts.ping_timeout_sec)
      ),
  )
  return AttemptLifecycleManagerAsync(
      client=client, opts=opts, process_uid=process_uid
  )


@dataclasses.dataclass(kw_only=True)
class LifecycleManagerCore(typing.Generic[_EventT, _ClientT]):
  """Behavior shared between the sync and async lifecycle managers.

  This class manages request construction, process UID generation, moving
  average latency tracking, and dynamic safety margin calculation. It does
  not perform any IO, thread, or task management.
  """

  # The active TurboCI state.
  client: _ClientT

  # All user configurable options.
  opts: HeartbeatOptions

  # An event, signalled when _on_state_change sees a new target heartbeat_by
  # from the Orchestrator. This will happen as a side effect of any write which
  # touches the current attempt (including heartbeat pings). The sole purpose
  # of this is to wake up the thread/task in the heartbeat loop so it can
  # re-assess it's delay time.
  #
  # The concrete event instance is set by the subclass.
  _target_heartbeat_by_changed: _EventT = dataclasses.field(init=False)

  # The last `heartbeat_by` value this lifecycle manager has been notified of.
  _observed_heartbeat_by: float = float("-inf")

  # Our actual target heartbeat_by (will be less than or equal to
  # observed_heartbeat_by).
  #
  # If this is None, then it means the Orchestrator does not need us to report
  # heartbeats, or that the subclass has decided to tear down. Once this is
  # None, it never becomes a float again.
  _target_heartbeat_by: None | float = float("-inf")

  # Indicates if this lifecycle manager has been used already.
  _used: bool = dataclasses.field(default=False, init=False)

  @property
  def is_cancelled(self) -> bool:
    return self.client.latest_attempt_state.HasField("cancelled_at")

  def assert_running(self):
    """Asserts that the current attempt is still RUNNING.

    Otherwise, raises errors.StageAttemptNotRunning.

    Call this to check if the attempt should tear down.

    Example:
      try:
        while working:
          lcm.assert_running()
      except client.StageAttemptNotRunning:
        pass
      finally:
        lcm.start_tearing_down()
        # do teardown.
    """
    st = self.client.latest_attempt_state
    if st.state != stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_RUNNING:
      if self.is_cancelled:
        delay = self.client.ts_as_float(st.cancelled_at.ts) - time.time()
        self.client.logger.info(f"Observed cancellation with delay: {delay}s")
      raise errors.StageAttemptNotRunning()

  def _make_incomplete_request(
      self,
      reason: str | None = None,
  ) -> write_nodes_request_pb2.WriteNodesRequest:
    req = write_nodes_request_pb2.WriteNodesRequest()
    if reason is not None:
      req.reason.message = reason
    else:
      req.reason.message = "execution_failed"

    req.current_attempt.state_transition.incomplete.SetInParent()
    return req

  def _make_complete_request(
      self,
      reason: str | None = None,
  ) -> write_nodes_request_pb2.WriteNodesRequest:
    req = write_nodes_request_pb2.WriteNodesRequest()
    if reason is not None:
      req.reason.message = reason
    else:
      req.reason.message = "execution_completed"

    req.current_attempt.state_transition.complete.SetInParent()
    return req

  def _get_exit_transition_request(
      self,
      exc_type: type[BaseException] | None,
      exc_val: BaseException | None,
  ) -> write_nodes_request_pb2.WriteNodesRequest | None:
    """Computes the WriteNodesRequest for context exit, if any."""
    if not self.opts.transition_on_exit:
      return None
    if self.client.latest_attempt_state.state in (
        stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_COMPLETE,
        stage_attempt_state_pb2.STAGE_ATTEMPT_STATE_INCOMPLETE,
    ):
      return None

    if exc_type is not None:
      self.client.logger.warning(
          "%s caught exception, transitioning attempt to INCOMPLETE: %s",
          type(self).__name__.lstrip("_"),
          exc_val,
      )
      reason = f"execution_failed: {exc_type.__name__}: {exc_val}"
      return self._make_incomplete_request(reason=reason[:1024])

    return self._make_complete_request()

  def _register(self):
    if self._used:
      raise RuntimeError(f"{type(self)} cannot be re-entered")
    self._used = True
    self.client.register_on_state_change(self._on_state_change)

  def _unregister(self):
    self.client.unregister_on_state_change(self._on_state_change)
    self._target_heartbeat_by = None
    self._target_heartbeat_by_changed.set()

  def _on_state_change(self, attempt_state: stage_pb2.StageAttemptCurrentState):
    """Processes the stage attempt state, updating target_heartbeat_by."""
    if self._target_heartbeat_by is None:
      return

    hbby = self.client.ts_as_float(attempt_state.heartbeat_by)
    if hbby > self._observed_heartbeat_by:
      self._observed_heartbeat_by = hbby
      delay = self.opts.calculate_delay(attempt_state)
      self._target_heartbeat_by = None if delay is None else time.time() + delay
      self._target_heartbeat_by_changed.set()

  def _handle_loop_error(self, e: Exception) -> None:
    if isinstance(e, errors.RetryableRPCError):
      self.opts.consecutive_unexpected_errors = 0
      self.client.logger.warning(
          "Transient heartbeat failure: %s. Retrying in %0.2fs.",
          e,
          self.opts.min_delay_sec,
      )
      return

    if isinstance(e, errors.RPCError):
      self.opts.consecutive_unexpected_errors = 0
      self.client.logger.error(
          "Permanent heartbeat failure: %s. Stopping heartbeat loop.", e
      )
      self._unregister()
      return

    self.opts.consecutive_unexpected_errors += 1
    if (
        self.opts.consecutive_unexpected_errors
        >= self.opts.max_consecutive_unexpected_errors
    ):
      self.client.logger.error(
          "Too many consecutive unexpected heartbeat failures (%d). Stopping"
          " heartbeat loop. Last error: %s",
          self.opts.consecutive_unexpected_errors,
          e,
      )
      self._unregister()
      return

    self.client.logger.warning(
        "Unexpected heartbeat failure: %s. Retrying in %0.2fs (attempt %d/%d).",
        e,
        self.opts.min_delay_sec,
        self.opts.consecutive_unexpected_errors,
        self.opts.max_consecutive_unexpected_errors,
    )


@typing.final
@dataclasses.dataclass(kw_only=True)
class AttemptLifecycleManager(
    LifecycleManagerCore[threading.Event, clients.Sync]
):
  """Sync Context manager for running and heartbeating a Stage Attempt.

  Usually you want to use `execute_stage` instead of directly constructing this.

  This class is specifically designed for use within Stage Executor service
  implementations to manage the lifecycle of a Stage Attempt.

  When constructed via `execute_stage`, the Attempt is transitioned to
  SCHEDULED or RUNNING. On enter, it registers for state updates and spawns a
  background thread to periodically send heartbeats if enabled by the
  Orchestrator. It supports adaptive safety margins, randomized jitter, and
  graceful cancellation detection.

  On exit, if `opts.transition_on_exit` is True (the default):
  - If an exception was raised, it automatically attempts to transition the
    Attempt to INCOMPLETE (unless already COMPLETE or INCOMPLETE).
  - Otherwise, it automatically attempts to transition the Attempt to COMPLETE
    (unless already COMPLETE or INCOMPLETE).

  See `execute_stage` for usage examples.
  """

  # The process_uid picked by execute_stage, for naming the thread.
  process_uid: str

  # Background thread running the periodic heartbeat loop.
  _thread: threading.Thread | None = dataclasses.field(default=None, init=False)

  def __post_init__(self):
    self._target_heartbeat_by_changed = threading.Event()

  def __enter__(self) -> AttemptLifecycleManager:
    self._register()
    if self._target_heartbeat_by is not None:
      self._thread = threading.Thread(
          target=self._loop,
          name=f"heartbeater-{self.process_uid}",
          daemon=True,
      )
      self._thread.start()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    _ = exc_tb
    self._unregister()
    if self._thread:
      self._thread.join(timeout=self.opts.exit_timeout_sec)
      if self._thread.is_alive():
        self.client.logger.warning(
            "Heartbeater thread failed to stop within %0.2fs",
            self.opts.exit_timeout_sec,
        )
      self._thread = None

    if req := self._get_exit_transition_request(exc_type, exc_val):
      try:
        self._ping(req)
      except Exception as e:
        target = "INCOMPLETE" if exc_type is not None else "COMPLETE"
        self.client.logger.error(
            "Failed to transition attempt to %s on exit: %s", target, e
        )

  def start_tearing_down(
      self,
      reason: str | None = None,
      details: typing.Sequence[value_write_pb2.ValueWrite] | None = None,
  ):
    """Transitions the current stage attempt to the TEARING_DOWN state.

    This call is serialized with any concurrent heartbeat writes.

    Args:
      reason: Optional custom status message. If None, a default reason is
        provided ("tearing_down" or "tearing_down[cancelled]").
      details: Optional sequence of ValueWrite details to send with the
        transition.
    """
    self._ping(
        _make_tearing_down_request(
            self.is_cancelled, reason=reason, details=details
        )
    )

  def _ping(self, req: write_nodes_request_pb2.WriteNodesRequest):
    """Sends a WriteNodes request, serializing it and tracking latency."""
    start = time.perf_counter()
    self.client.WriteNodes(
        req,
        options=transports.CallOptions(
            deadline=datetime.timedelta(seconds=self.opts.ping_timeout_sec)
        ),
    )
    self.opts.record_latency(time.perf_counter() - start)

  def _loop(self):
    while True:
      self._target_heartbeat_by_changed.clear()
      target_time = self._target_heartbeat_by
      if target_time is None:
        return

      event_fired = self._target_heartbeat_by_changed.wait(
          timeout=target_time - time.time()
      )
      if event_fired:
        continue
      try:
        self._ping(_make_heartbeat_request())
      except Exception as e:
        self._handle_loop_error(e)


@typing.final
@dataclasses.dataclass(kw_only=True)
class AttemptLifecycleManagerAsync(
    LifecycleManagerCore[asyncio.Event, clients.Async]
):
  """Async Context manager for running and heartbeating a Stage Attempt.

  Usually you want to use `async_execute_stage` instead of directly constructing
  this.

  This class is specifically designed for use within Stage Executor service
  implementations to manage the lifecycle of a Stage Attempt.

  When constructed via `async_execute_stage`, the Attempt is transitioned to
  SCHEDULED or RUNNING. On aenter, it registers for state updates and spawns a
  background asyncio task to periodically send heartbeats if enabled by the
  Orchestrator. It supports adaptive safety margins, randomized jitter, and
  graceful cancellation detection.

  On exit, if `opts.transition_on_exit` is True (the default):
  - If an exception was raised, it automatically attempts to transition the
    Attempt to INCOMPLETE (unless already COMPLETE or INCOMPLETE).
  - Otherwise, it automatically attempts to transition the Attempt to COMPLETE
    (unless already COMPLETE or INCOMPLETE).

  See `async_execute_stage` for usage examples.
  """

  # The process_uid picked by async_execute_stage, for naming the task.
  process_uid: str

  # Background asyncio task running the periodic heartbeat loop.
  _task: asyncio.Task | None = dataclasses.field(default=None, init=False)

  def __post_init__(self):
    self._target_heartbeat_by_changed = asyncio.Event()

  async def __aenter__(self) -> AttemptLifecycleManagerAsync:
    self._register()
    if self._target_heartbeat_by is not None:
      self._task = asyncio.create_task(
          self._loop(),
          name=f"heartbeater-{self.process_uid}",
      )
    return self

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    _ = exc_tb
    self._unregister()
    if self._task:
      self._task.cancel()
      try:
        async with asyncio.timeout(self.opts.exit_timeout_sec):
          await self._task
      except TimeoutError:
        self.client.logger.warning(
            "Heartbeater task failed to stop within %0.2fs",
            self.opts.exit_timeout_sec,
        )
      except asyncio.CancelledError:
        pass
      finally:
        self._task = None

    if req := self._get_exit_transition_request(exc_type, exc_val):
      try:
        await self._ping(req)
      except Exception as e:
        target = "INCOMPLETE" if exc_type is not None else "COMPLETE"
        self.client.logger.error(
            "Failed to transition attempt to %s on exit: %s", target, e
        )

  async def start_tearing_down(
      self,
      reason: str | None = None,
      details: typing.Sequence[value_write_pb2.ValueWrite] | None = None,
  ):
    """Transitions the current stage attempt to the TEARING_DOWN state.

    This call is serialized with any concurrent heartbeat writes.

    Args:
      reason: Optional custom status message. If None, a default reason is
        provided ("tearing_down" or "tearing_down[cancelled]").
      details: Optional sequence of ValueWrite details to send with the
        transition.
    """
    await self._ping(
        _make_tearing_down_request(
            self.is_cancelled, reason=reason, details=details
        )
    )

  async def _ping(self, req: write_nodes_request_pb2.WriteNodesRequest):
    """Sends a WriteNodes request, serializing it and tracking latency."""
    start = time.perf_counter()
    await self.client.WriteNodes(
        req,
        options=transports.CallOptions(
            deadline=datetime.timedelta(seconds=self.opts.ping_timeout_sec)
        ),
    )
    self.opts.record_latency(time.perf_counter() - start)

  async def _loop(self):
    while True:
      self._target_heartbeat_by_changed.clear()
      target_time = self._target_heartbeat_by
      if target_time is None:
        return

      try:
        await asyncio.wait_for(
            self._target_heartbeat_by_changed.wait(),
            timeout=target_time - time.time(),
        )
        # The event fired, so loop around again.
        continue
      except asyncio.TimeoutError:
        # We timed out waiting for the event, so do the ping.
        try:
          await self._ping(_make_heartbeat_request())
        except Exception as e:
          self._handle_loop_error(e)
