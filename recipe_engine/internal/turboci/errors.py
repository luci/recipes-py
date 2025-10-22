# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Provides error types for turboci."""

from PB.turboci.graph.orchestrator.v1.transaction_invariant import TransactionConflictFailure


class TurboCIException(Exception):
  """Base class for all TurboCI exceptions."""


class TransactionConflictException(TurboCIException):
  """Raised when a WriteNodes or a QueryNodes with version.require set
  encounters a node which is newer than the transaction start time."""

  def __init__(self, *args: object,
               failure_message: TransactionConflictFailure) -> None:
    # failure_message is the underlying TransactionConflictFailure returned from
    # the service.
    self.failure_message = failure_message
    super().__init__(*args)


class CheckWriteInvariantException(TurboCIException):
  """Raised when attempting to apply a CheckWrite to a Check
  which would violate some invariant (e.g. attempting to mutate options on
  a PLANNED Check)."""


class InvalidArgumentException(TurboCIException):
  """Raised when the input arguments were invalid.

  Corresponds to gRPC code INVALID_ARGUMENT.
  """


class TransactionUseAfterWriteException(TurboCIException):
  """Raised from Transaction.WriteNodes/QueryNodes if they are called after
  a call to WriteNodes."""
