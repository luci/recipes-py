# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tracks observed nodes for transactions."""

from __future__ import annotations

import copy
import dataclasses
import threading
import typing

from google.protobuf import message
from google.protobuf import timestamp_pb2
from PB.turboci.graph.ids.v1 import identifier as identifier_pb2
from PB.turboci.graph.orchestrator.v1 import check as check_pb2
from PB.turboci.graph.orchestrator.v1 import query_nodes_request as query_nodes_request_pb2
from PB.turboci.graph.orchestrator.v1 import query_nodes_response as query_nodes_response_pb2
from PB.turboci.graph.orchestrator.v1 import read_workplan_response as read_workplan_response_pb2
from PB.turboci.graph.orchestrator.v1 import revision as revision_pb2
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb2
from PB.turboci.graph.orchestrator.v1 import transaction_details as transaction_details_pb2
from PB.turboci.graph.orchestrator.v1 import workplan as workplan_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_request as write_nodes_request_pb2
from PB.turboci.graph.orchestrator.v1 import write_nodes_response as write_nodes_response_pb2
from turboci.utils import ids
from turboci.utils import value
from turboci.utils.client import clients
from turboci.utils.client import errors
from turboci.utils.client import state

__all__ = [
    'ObservedNodeSet',
    'Transactional',
    'TransactionalAsync',
    'run_transaction',
    'run_transaction_async',
]

ObservableNode = stage_pb2.Stage | check_pb2.Check | stage_pb2.Stage.Attempt

ObservableNodeID = (
    identifier_pb2.Stage | identifier_pb2.Check | identifier_pb2.StageAttempt
)


@dataclasses.dataclass
class ObservedNodeSet:
  """Tracks nodes (checks, stages, attempts) observed as part of a transaction.

  This set can then be turned into a precondition for a WriteNodes request.
  """

  # The WorkPlan that this ObservedNodeSet is bound to.
  wpid: identifier_pb2.WorkPlan

  # The set of nodes observed - these are the identifiers of the nodes encoded
  # with `ids.to_string`.
  _nodes: set[str] = dataclasses.field(default_factory=set, init=False)

  # The revision of the workplan which we observed during the first observed
  # response.
  #
  # If we do a WriteNodes call with `_nodes` set, but this as `None`, it's the
  # same as asserting "the nodes do not exist".
  _rev: None | revision_pb2.Revision = dataclasses.field(
      default=None, init=False
  )

  @property
  def nodes(self) -> frozenset[str]:
    """Returns a read-only view of the observed nodes."""
    return frozenset(self._nodes)

  def assert_missing_nodes(self, *nodes: ObservableNodeID):
    """Adds `nodes` to our observed set as not existing in the WorkPlan yet.

    May only be used if `_rev` is None (i.e. no read/query has been done yet).

    If you want to query, then instead include these nodes as part of the
    query's nodes_by_id, and they will be marked as missing (if they actually
    are missing in the response).
    """
    if self._rev:
      raise ValueError('cannot assert_missing_nodes after doing read/query')
    for node in nodes:
      self._observe(node)

  def observe_QueryNodes(
      self,
      req: query_nodes_request_pb2.QueryNodesRequest,
      rsp: query_nodes_response_pb2.QueryNodesResponse,
  ):
    """Adds all explicitly requested nodes, and all observed nodes to the set.

    Response and request must only contain nodes belonging to the
    ObservedNodeSet's bound WorkPlan.
    """
    for wp in rsp.workplans:
      self._observe_workplan(wp)
    for q in req.query:
      if q.HasField('nodes_by_id'):
        for node in q.nodes_by_id.nodes:
          match x := ids.unwrap(node):
            case (
                identifier_pb2.Stage()
                | identifier_pb2.StageAttempt()
                | identifier_pb2.Check()
            ):
              self._observe(x)

  def observe_ReadWorkPlan(
      self,
      rsp: read_workplan_response_pb2.ReadWorkPlanResponse,
  ):
    """Adds all observed nodes to the set.

    Request must only contain nodes belonging to the ObservedNodeSet's bound
    WorkPlan.
    """
    self._observe_workplan(rsp.workplan)

  def _observe_workplan(self, wp: workplan_pb2.WorkPlan):
    """Adds all nodes in the WorkPlan to the observed set.

    If this is the first response observed, then `_rev` is set to `wp.version`.

    Otherwise, if any of the observed nodes have a version greater than
    `_rev`, this raises TransactionalPreconditionError.

    Raises:
      * ValueError if called after assert_missing_nodes.
      * ValueError if wp contains nodes from a different WorkPlan.
      * TransactionalPreconditionError if wp contains nodes whose version
        is greater than `_rev`.
    """
    if not self._rev:
      if self._nodes:
        raise ValueError('cannot read/query after `assert_missing_nodes`')
      self._rev = wp.version

    for check in wp.checks:
      self._assert_older_or_same(check)
      self._observe(check.identifier)

    for stage in wp.stages:
      self._assert_older_or_same(stage)
      self._observe(stage.identifier)

      for attempt in stage.attempts:
        if attempt.HasField('version'):
          self._assert_older_or_same(attempt)
          self._observe(attempt.identifier)

  def _assert_older_or_same(self, node: ObservableNode):
    assert self._rev
    if self._is_after(node.version, self._rev):
      cvers = self._ts_to_str(node.version.ts)
      wpvers = self._ts_to_str(self._rev.ts)
      ident = ids.to_string(node.identifier)
      raise errors.TransactionalPreconditionError.make(
          f'node[{ident!r}]: newer than snapshot: {cvers} > {wpvers}'
      )

  def _observe(self, ident: ObservableNodeID):
    """Observes a single node.

    If the node has a WorkPlan id, it must match the ObservedNodeSet's bound
    WorkPlan (or this will raise ValueError).

    Raises:
      * ValueError if wp contains nodes from a different WorkPlan.
    """
    curwp, _, _ = ids.root(ident)
    if curwp and curwp != self.wpid:
      cur, bound = ids.to_string(curwp), ids.to_string(self.wpid)
      raise ValueError(
          f'transaction observed multiple workplans: {cur!r} != {bound!r}'
      )
    elif curwp:
      ident = ids.clear_workplan(copy.deepcopy(ident))
    self._nodes.add(ids.to_string(ident))

  def generate_precondition(self) -> transaction_details_pb2.TransactionDetails:
    """Generates a TransactionDetails proto from the observed nodes."""
    txn = transaction_details_pb2.TransactionDetails(
        snapshot_version=self._rev,
    )
    for node_str in sorted(self._nodes):
      txn.nodes_observed.append(ids.from_string(node_str))
    return txn

  @staticmethod
  def _is_after(a: revision_pb2.Revision, b: revision_pb2.Revision) -> bool:
    return (a.ts.seconds, a.ts.nanos) > (b.ts.seconds, b.ts.nanos)

  @staticmethod
  def _ts_to_str(ts: timestamp_pb2.Timestamp) -> str:
    return f'{ts.seconds}/{ts.nanos}'


# LocalNodePredicate is the type signature for a filter function used with
# `apply_node_predicate`.
#
# This should be a pure function over its arguments.
LocalNodePredicate = typing.Callable[
    [value.DataSource, check_pb2.Check | stage_pb2.Stage], bool
]


def apply_node_predicate(
    pred: LocalNodePredicate,
    plans: workplan_pb2.WorkPlan | typing.Sequence[workplan_pb2.WorkPlan],
    data: value.MutableDataSource,
):
  """Modifies `data` and `plans` to remove items where `pred` returns False.

  Also discards value_data which ar unreferenced after the removal of all nodes
  which reference it.

  The intent is to be able to filter one or more API-returned workplans before
  passing them for observation to a ObservedNodeSet (e.g. to remove nodes from a
  ReadWorkPlanResponse which are not relevant to the transaction).
  """
  if isinstance(plans, workplan_pb2.WorkPlan):
    plans = (plans,)

  data_to_remove: set[str] = set(data)
  for wp in plans:
    for i, check in reversed(list(enumerate(wp.checks))):
      if pred(data, check):
        for _, ref in value.refs_in_check(check):
          data_to_remove.discard(ref.digest)
        continue
      wp.checks.pop(i)
    for i, stage in reversed(list(enumerate(wp.stages))):
      if pred(data, stage):
        for _, ref in value.refs_in_stage(stage):
          data_to_remove.discard(ref.digest)
        continue
      wp.stages.pop(i)
  for digest in data_to_remove:
    del data[digest]


_LockT = typing.TypeVar('_LockT', bound=typing.ContextManager[typing.Any])


@dataclasses.dataclass(kw_only=True)
class _TransactionalBase(state.State[_LockT], typing.Generic[_LockT]):
  """Base class for transactional clients, holding shared state and hooks."""

  _observed: ObservedNodeSet = dataclasses.field(init=False)
  _write_called: list[bool] = dataclasses.field(
      default_factory=lambda: [False], init=False
  )
  _node_filter: LocalNodePredicate | None = dataclasses.field(
      default=None, init=False
  )

  def __post_init__(self):
    # Safe call to parent __post_init__ if it exists in MRO.
    # Needed for cooperative multiple inheritance, as clients.Sync/Async
    # do not currently define __post_init__.
    if hasattr(super(), '__post_init__'):
      super().__post_init__()  # type: ignore
    self._observed = ObservedNodeSet(wpid=self.wpid)

  def with_node_filter(self, pred: LocalNodePredicate) -> typing.Self:
    """Returns a shallow copy of the client with the given node filter applied.

    The predicate is used to determine which nodes to keep. Any nodes discard
    will be removed from the response (and any now-unreferenced data as well)
    before they are observed by the transaction.

    This is useful for excluding irrelevant nodes that shouldn't trigger
    transaction conflicts if they happen to change between read and write.

    Args:
      pred: A predicate function that returns True for nodes to *keep*.
    """
    new_client = copy.copy(self)
    new_client._node_filter = pred  # pylint: disable=protected-access
    return new_client

  def assert_missing_nodes(self, *nodes: ObservableNodeID):
    """Asserts that the given nodes do not exist in the WorkPlan yet.

    This may only be called before any read or query operations are performed
    on this transactional client, and prevents all future reads.

    If you want to query, then instead include these nodes as part of the
    query's nodes_by_id, and they will be marked as missing (if they actually
    are missing in the response).

    Args:
      *nodes: The node identifiers to assert as missing.
    """
    self._observed.assert_missing_nodes(*nodes)

  def _adjust_request_precondition(self, req: message.Message) -> None:
    if isinstance(req, write_nodes_request_pb2.WriteNodesRequest):
      if self._write_called[0]:
        raise errors.TransactionMultipleWritesError(
            'transactional client used for more than one write'
        )
      req.txn.CopyFrom(self._observed.generate_precondition())

  def _process_response_observed_nodes(
      self, req: message.Message, rsp: message.Message
  ) -> None:
    match rsp:
      case read_workplan_response_pb2.ReadWorkPlanResponse():
        if self._node_filter:
          apply_node_predicate(self._node_filter, rsp.workplan, self.data)
        self._observed.observe_ReadWorkPlan(rsp)

      case query_nodes_response_pb2.QueryNodesResponse():
        assert isinstance(req, query_nodes_request_pb2.QueryNodesRequest)
        if self._node_filter:
          apply_node_predicate(self._node_filter, rsp.workplans, self.data)
        self._observed.observe_QueryNodes(req, rsp)

      case write_nodes_response_pb2.WriteNodesResponse():
        self._write_called[0] = True


@dataclasses.dataclass(kw_only=True)
class Transactional(_TransactionalBase[threading.Lock], clients.Sync):
  """Transactional synchronous client for TurboCI Orchestrator."""


@dataclasses.dataclass(kw_only=True)
class TransactionalAsync(_TransactionalBase[state.NullLock], clients.Async):
  """Transactional asynchronous client for TurboCI Orchestrator."""


T = typing.TypeVar('T')


def run_transaction(
    client: clients.Sync,
    callback: typing.Callable[[Transactional], T],
    *,
    max_retries: int = 5,
) -> T:
  """Runs a transaction using the given sync client.

  Derives a Transactional client from the base client and passes it to
  the callback. If the callback raises TransactionalPreconditionError,
  it will be retried up to max_retries times.

  Args:
    client: The base sync client.
    callback: The transaction body, accepting the transactional client.
    max_retries: Maximum number of retries.
  """
  max_retries = max(0, max_retries)
  for attempt in range(max_retries + 1):
    # pylint: disable=unexpected-keyword-arg
    tx_client = Transactional(
        wpid=client.wpid,
        transport=client.transport,
        data=client.data,
    )
    try:
      return callback(tx_client)
    except errors.RPCError as exc:
      if not exc.status.conflict:
        raise
      if attempt < max_retries:
        client.logger.warning(
            'Retrying transaction (attempt %d/%d) due to precondition'
            ' conflict: %s',
            attempt + 1,
            max_retries,
            exc,
        )
        continue
      raise
  raise Exception('impossible')


async def run_transaction_async(
    client: clients.Async,
    callback: typing.Callable[[TransactionalAsync], typing.Awaitable[T]],
    *,
    max_retries: int = 5,
) -> T:
  """Runs a transaction using the given async client.

  Derives a TransactionalAsync client from the base client and passes it to
  the callback. If the callback raises TransactionalPreconditionError,
  it will be retried up to max_retries times.

  Args:
    client: The base async client.
    callback: The transaction body, accepting the transactional client.
    max_retries: Maximum number of retries.
  """
  max_retries = max(0, max_retries)
  for attempt in range(max_retries + 1):
    # pylint: disable=unexpected-keyword-arg
    tx_client = TransactionalAsync(
        wpid=client.wpid,
        transport=client.transport,
        data=client.data,
    )
    try:
      return await callback(tx_client)
    except errors.TransactionalPreconditionError as exc:
      if attempt < max_retries:
        client.logger.warning(
            'Retrying transaction (attempt %d/%d) due to precondition'
            ' conflict: %s',
            attempt + 1,
            max_retries,
            exc,
        )
        continue
      raise
  raise Exception('impossible')
