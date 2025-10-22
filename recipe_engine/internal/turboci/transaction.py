# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence

from google.protobuf.message import Message

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check_view import CheckView
from PB.turboci.graph.orchestrator.v1.graph_view import GraphView
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest

from . import common
from .ids import from_id, to_id
from .errors import TransactionConflictException, TransactionUseAfterWriteException


@dataclass
class Transaction:
  """Stores state related to a single transaction.

  This allows multiple `query` calls, followed by at most one `write` call.

  Note that you should not rely on data which is read as part of this
  transaction until after the transaction has been successfully committed.
  """

  # The real (or fake) TurboCIClient implementation.
  _client: common.TurboCIClient

  # The mode for queries on this Transaction.
  _query_mode: QueryMode

  # A set of node IDs which have been observed in this Transaction.
  #
  # This will include all nodes returned from any QueryNodes calls made in
  # this Transaction.
  observed_nodes: set[str] = field(default_factory=set)

  # The pinned revision for this Transaction.
  #
  # Set on the first query.
  #
  # When `write_nodes` is used (or `query_nodes` in "require" mode), if any
  # nodes being written or in `observed_nodes` have a revision which is newer
  # than this, the function will raise TransactionConflictException.
  _revision: Revision | None = None

  # A given Transaction can only do a single write at the end.
  #
  # If you need to chain transactions together, you need multiple
  # `run_transaction` calls.
  #
  # This is not necessary to enforce for the local fake, however it will be
  # necessary for correctness for the live service.
  _did_write: bool = False

  def _observe_graph(self, graph: GraphView):
    if not self._revision:
      self._revision = graph.version

    # checks
    for view in graph.checks:
      self.observed_nodes.add(from_id(view.check.identifier))
      for datum in view.option_data:
        self.observed_nodes.add(from_id(datum.identifier))
      for result in view.results:
        for datum in result.data:
          self.observed_nodes.add(from_id(datum.identifier))

    # stages
    for view in graph.stages:
      self.observed_nodes.add(from_id(view.stage.identifier))

  def write_nodes(
      self,
      *nodes_reasons: (
        WriteNodesRequest.CheckWrite|
        WriteNodesRequest.StageWrite|
        WriteNodesRequest.Reason),

      current_stage: WriteNodesRequest.CurrentStageWrite|None = None,
  ) -> None:
    """Writes one or more nodes.

    Once called, this Transaction object must be discarded. If you want to do
    a second transaction, call `run_transaction` again.
    """
    if self._did_write:
      raise TransactionUseAfterWriteException("WriteNodes called twice.")
    self._did_write = True

    txn: WriteNodesRequest.TransactionDetails|None = None
    if self._revision:
      txn = WriteNodesRequest.TransactionDetails(
          nodes_observed=(to_id(node) for node in self.observed_nodes),
          snapshot_version=self._revision,
      )

    req = WriteNodesRequest(
        current_stage=current_stage,
        txn=txn,
    )
    for node in nodes_reasons:
      match node:
        case WriteNodesRequest.CheckWrite():
          req.checks.append(node)
        case WriteNodesRequest.StageWrite():
          req.stages.append(node)
        case _:
          req.reasons.append(node)

    self._client.WriteNodes(req)

  def query_nodes(self, *query: Query, observe_graph = True) -> GraphView:
    """Runs run or more queries and returns their combined result.

    Will add all observed nodes to Transaction.observed_nodes unless
    `observe_graph` is False.
    """
    if self._did_write:
      raise TransactionUseAfterWriteException("QueryNodes called after WriteNodes.")

    req = QueryNodesRequest()
    if self._revision:
      match self._query_mode:
        case 'require':
          req.version.require.CopyFrom(self._revision)
        case 'snapshot':
          req.version.snapshot.CopyFrom(self._revision)
    req.query.extend(query)
    rsp = self._client.QueryNodes(req)
    if observe_graph:
      self._observe_graph(rsp.graph)
      for absent in rsp.absent:
        self.observed_nodes.add(from_id(absent))
    return rsp.graph

  def read_checks(
      self,
      *ids: identifier.Check|str,
      collect: Query.Collect.Check|None = None,
      types: Sequence[str|Message|type[Message]] = ()
  ) -> Sequence[CheckView]:
    """Convenience function for reading one or more checks by ID.

    This just does a query_nodes for the ids specified by `ids`, and then unwraps
    the result.
    """
    return self.query_nodes(common.make_query(
        Query.Select(nodes=common.collect_check_ids(*ids)),
        collect,
        types=types,
    )).checks


# The mode for QueryNodes's version restriction.
#   * require - query_nodes will raise an RpcError if any of the nodes that
#     would be returned are newer than this Transaction's snapshot revision,
#     and the transaction will immediately retry.
#   * snapshot - query_nodes will return values consistent with the
#     Transaction's first query - but if anything in the observed_nodes set
#     changed by the time you do write_nodes, the write_nodes will still
#     raise RpcError and trigger a transaction retry.
#     (Note: the fake doesn't currently support this mode).
QueryMode = Literal['require', 'snapshot']


def run_transaction(
    txnFunc: Callable[[Transaction], None],
    *,
    retries=3,
    client: common.TurboCIClient | None = None,
    query_mode: QueryMode = 'require',
):
  """Runs the function `txnFunc` up to `retries` number of times,
  retrying TransactionConflictFailures.

  This function should use the provided Transaction to do some number of
  queries, followed by at most one write.
  """
  if not client:
    client = common.CLIENT
  for attempt in range(retries):
    txn = Transaction(client, query_mode)
    try:
      txnFunc(txn)
      return
    except TransactionConflictException:
      if attempt == retries-1:
        raise
