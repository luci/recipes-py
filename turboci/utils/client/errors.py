# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unified error types and translation helpers for TurboCI Orchestrator."""

from __future__ import annotations

from google.protobuf import json_format
from google.rpc import code_pb2
from google.rpc import status_pb2
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb2
from PB.turboci.graph.orchestrator.v1 import transaction_invariant as transaction_invariant_pb2

__all__ = [
    'MakeRPCError',
    'ParsedRPCStatus',
    'RPCError',
    'RetryableRPCError',
    'StageAttemptAlreadyClaimedError',
    'StageAttemptNotRunning',
    'TransactionMultipleWritesError',
    'TransactionalPreconditionError',
]


class ParsedRPCStatus:
  """Parsed status_pb2.Status with the TurboCI-relevant pieces extracted."""

  def __init__(self, status: status_pb2.Status | None):
    current_state: stage_pb2.StageAttemptCurrentState | None = None
    claim_failure: stage_pb2.StageAttemptClaimedFailure | None = None
    conflict: transaction_invariant_pb2.TransactionConflictFailure | None = None
    code: int | None = None
    if status:
      code = status.code
      for detail in status.details:
        if detail.Is(stage_pb2.StageAttemptCurrentState.DESCRIPTOR):
          current_state = stage_pb2.StageAttemptCurrentState()
          detail.Unpack(current_state)
        elif detail.Is(stage_pb2.StageAttemptClaimedFailure.DESCRIPTOR):
          claim_failure = stage_pb2.StageAttemptClaimedFailure()
          detail.Unpack(claim_failure)
        elif detail.Is(
            transaction_invariant_pb2.TransactionConflictFailure.DESCRIPTOR
        ):
          conflict = transaction_invariant_pb2.TransactionConflictFailure()
          detail.Unpack(conflict)
        if current_state and claim_failure and conflict:
          break

    self.code = code
    self.raw = status
    self.current_state = current_state
    self.claim_failure = claim_failure
    self.conflict = conflict

  @property
  def retryable(self) -> bool:
    """Returns True for retriable codes."""
    return not self.conflict and self.code in (
        code_pb2.ABORTED,
        code_pb2.CANCELLED,
        code_pb2.DEADLINE_EXCEEDED,
        code_pb2.INTERNAL,
        code_pb2.RESOURCE_EXHAUSTED,
        code_pb2.UNAVAILABLE,
        code_pb2.UNKNOWN,
    )


def MakeRPCError(
    message: str, status: status_pb2.Status | None = None
) -> RPCError:
  """Returns an RPCError (or a subclass) given the message and status."""
  pstat = ParsedRPCStatus(status)

  if pstat.conflict:
    return TransactionalPreconditionError(message, pstat)

  if pstat.claim_failure:
    return StageAttemptAlreadyClaimedError(message, pstat)

  if pstat.retryable:
    return RetryableRPCError(message, pstat)

  return RPCError(message, pstat)


class RPCError(Exception):
  """Unified error for Turbo CI Orchestrator Transports.

  Correctly implemented transports must raise this exception.

  Use `MakeRPCError` to construct this exception. It will automatically
  return the most appropriate subclass based on `status`.
  """

  def __init__(self, message: str, pstat: ParsedRPCStatus):
    msg_parts = []
    if pstat.code:
      msg_parts.append(f'{code_pb2.Code.Name(pstat.code)}: {message}')
    else:
      msg_parts.append(message)
    if pstat.current_state:
      cstate = json_format.MessageToJson(pstat.current_state, indent=None)
      msg_parts.append(f'  attempt_state: {cstate}')
    if pstat.claim_failure:
      msg_parts.append(
          f'  claimed_by: {pstat.claim_failure.claimed_by_process_uid!r}'
      )
    if pstat.conflict:
      msg_parts.append('  txn conflict: True')
    super().__init__('\n'.join(msg_parts))
    self.status = pstat

  @staticmethod
  def make(
      msg: str, code: code_pb2.Code = code_pb2.FAILED_PRECONDITION
  ) -> RPCError:
    """Make a basic RPCError.

    Mostly useful for tests and fakes.
    """
    pstat = ParsedRPCStatus(status_pb2.Status(code=code))
    if pstat.retryable:
      raise ValueError(f'Bad code {code_pb2.Code.Name(code)} - retryable')
    return RPCError(msg, pstat)


class RetryableRPCError(RPCError):
  """An RPCError which is known to be retriable."""

  @staticmethod
  def make(
      msg: str, code: code_pb2.Code = code_pb2.UNAVAILABLE
  ) -> RetryableRPCError:
    """Make a basic RetryableRPCError.

    Mostly useful for tests and fakes.
    """
    pstat = ParsedRPCStatus(status_pb2.Status(code=code))
    if not pstat.retryable:
      raise ValueError(f'Bad code {code_pb2.Code.Name(code)} - not retryable')
    return RetryableRPCError(msg, pstat)


class StageAttemptAlreadyClaimedError(RPCError):
  """An RPCError which indicates that the attempt is claimed by another process.

  This will occur when attempting to transition the current attempt to RUNNING,
  but the orchestrator already shows this attempt as RUNNING with a different
  process_uid. This most likely indicates a race in the way the executor
  dispatches work to runners such that multiple runners attempted to execute the
  same stage attempt.

  The process which observes this StageAttemptAlreadyClaimedError should exit
  gracefully without attempting to do any of the attempt's work and without
  attempting to interact with the WorkPlan.
  """

  @staticmethod
  def make(
      msg: str,
      code: code_pb2.Code = code_pb2.FAILED_PRECONDITION,
      claimed_process_uid: str = 'other-fake-process_uid',
  ) -> StageAttemptAlreadyClaimedError:
    """Make a basic StageAttemptAlreadyClaimedError.

    Mostly useful for tests and fakes.
    """
    st = status_pb2.Status(code=code)
    st.details.add().Pack(
        stage_pb2.StageAttemptClaimedFailure(
            claimed_by_process_uid=claimed_process_uid
        ),
    )
    return StageAttemptAlreadyClaimedError(msg, ParsedRPCStatus(st))


class TransactionalPreconditionError(RPCError):
  """An RPCError which indicates a failed transaction.

  This will occur on reads when a second read re-observes a node at a newer
  state, or on writes if some of the nodes in the precondition are actually
  at a newer state than what we observed.

  The transaction runner will catch this to start the transaction callback from
  the beginning.
  """

  @staticmethod
  def make(
      msg: str,
      code: code_pb2.Code = code_pb2.FAILED_PRECONDITION,
  ) -> TransactionalPreconditionError:
    """Make a basic TransactionalPreconditionError.

    Mostly useful for tests and fakes.
    """
    st = status_pb2.Status(code=code)
    st.details.add().Pack(
        transaction_invariant_pb2.TransactionConflictFailure()
    )
    return TransactionalPreconditionError(msg, ParsedRPCStatus(st))


class TransactionMultipleWritesError(Exception):
  """Multiple WriteNodes invocations were used in the same transaction attempt.

  This is not allowed - all writes must be done in a single WriteNodes call
  with the aggregated precondition.

  If you need to do multiple writes, split your transaction into multiple
  pieces, each of them independently observing the necessary precondition for
  that write.
  """


class StageAttemptNotRunning(Exception):
  """Raised from Heartbeater{,Async}.assert_running()."""
