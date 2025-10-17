# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Provides error types for turboci."""

from dataclasses import dataclass

from PB.turboci.graph.orchestrator.v1.transaction_invariant import TransactionConflictFailure


class TurboCIException(Exception):
  """Base class for all TurboCI exceptions."""


@dataclass
class TransactionConflictException(TurboCIException):
  """Raised when a WriteNodes or a QueryNodes with version.require set
  encounters a node which is newer than the transaction start time."""

  # failure_message is the underlying TransactionConflictFailure returned from
  # the service.
  failure_message: TransactionConflictFailure


class TransactionUseAfterWriteException(TurboCIException):
  """Raised from Transaction.WriteNodes/QueryNodes if they are called after
  a call to WriteNodes."""
