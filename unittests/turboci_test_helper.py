#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from typing import Callable, Sequence

import test_env

from google.protobuf.message import Message

from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest

from recipe_engine import turboci
from recipe_engine.internal.turboci.fake import FakeTurboCIOrchestrator
from recipe_engine.internal.turboci.transaction import QueryMode


class TestBaseClass(test_env.RecipeEngineUnitTest):

  def setUp(self):
    self.CLIENT = FakeTurboCIOrchestrator(test_mode=True)
    return super().setUp()

  def tearDown(self):
    self.CLIENT = None
    return super().tearDown()

  def write_nodes(
      self,
      *nodes: (WriteNodesRequest.CheckWrite | WriteNodesRequest.StageWrite
               | WriteNodesRequest.Reason),
      current_stage: WriteNodesRequest.CurrentStageWrite | None = None,
      txn: WriteNodesRequest.TransactionDetails | None = None,
  ):
    if not any(isinstance(node, WriteNodesRequest.Reason) for node in nodes):
      nodes += (turboci.reason('test write'),)
    return turboci.write_nodes(
        *nodes, current_stage=current_stage, txn=txn, client=self.CLIENT)

  def query_nodes(
      self,
      *queries: Query,
      version: QueryNodesRequest.VersionRestriction | None = None,
      types: Sequence[str | Message | type[Message]] = (),
  ):
    return turboci.query_nodes(
        *queries, version=version, types=types, client=self.CLIENT)

  def read_checks(
      self,
      *ids: identifier.Check | str,
      collect: Query.Collect.Check | None = None,
      types: Sequence[str | Message | type[Message]] = (),
  ):
    return turboci.read_checks(
        *ids, types=types, collect=collect, client=self.CLIENT)

  def run_transaction(
      self,
      txnFunc: Callable[[turboci.Transaction], None],
      *,
      retries=3,
      query_mode: QueryMode = 'require',
  ):
    return turboci.run_transaction(
        txnFunc, retries=retries, query_mode=query_mode, client=self.CLIENT)
