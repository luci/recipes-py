#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Sequence

import test_env

from google.protobuf import message
from turboci.utils import ids

from PB.turboci.graph.ids.v1 import identifier as identifier_pb
from PB.turboci.graph.orchestrator.v1 import check as check_pb
from PB.turboci.graph.orchestrator.v1 import query as query_pb
from PB.turboci.graph.orchestrator.v1 import (
    query_nodes_request as query_nodes_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    query_nodes_response as query_nodes_response_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    transaction_details as transaction_details_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_request as write_nodes_request_pb,
)
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_response as write_nodes_response_pb,
)

from recipe_engine import turboci
from recipe_engine.internal.turboci import fake


class TestBaseClass(test_env.RecipeEngineUnitTest):

  def setUp(self) -> None:
    self.CLIENT = fake.FakeTurboCIOrchestrator(test_mode=True)
    return super().setUp()

  def tearDown(self) -> None:
    self.CLIENT = None
    return super().tearDown()

  def write_nodes(
      self,
      *nodes: (
          write_nodes_request_pb.WriteNodesRequest.CheckWrite
          | write_nodes_request_pb.WriteNodesRequest.StageWrite
          | write_nodes_request_pb.WriteNodesRequest.Reason
      ),
      current_stage: (
          write_nodes_request_pb.WriteNodesRequest.CurrentStageWrite | None
      ) = None,
      txn: transaction_details_pb.TransactionDetails | None = None,
  ) -> write_nodes_response_pb.WriteNodesResponse:
    if not any(
        isinstance(node, write_nodes_request_pb.WriteNodesRequest.Reason)
        for node in nodes
    ):
      nodes += (turboci.reason('test write'),)
    return turboci.write_nodes(
        *nodes, current_stage=current_stage, txn=txn, client=self.CLIENT)

  def query_nodes(
      self,
      *queries: query_pb.Query,
      version: (
          query_nodes_request_pb.QueryNodesRequest.VersionRestriction | None
      ) = None,
      types: Sequence[str | message.Message | type[message.Message]] = (),
  ) -> query_nodes_response_pb.QueryNodesResponse:
    return turboci.query_nodes(
        *queries, version=version, types=types, client=self.CLIENT)

  def read_checks(
      self,
      *ids: identifier_pb.Check | str,
      collect: query_pb.Query.CollectChecks | None = None,
      types: Sequence[str | message.Message | type[message.Message]] = (),
  ) -> Sequence[check_pb.Check]:
    return turboci.read_checks(
        *ids, types=types, collect=collect, client=self.CLIENT)

  def check_ids(self, checks: Sequence[check_pb.Check]) -> set[str]:
    return set([ids.to_string(c.identifier) for c in checks])
