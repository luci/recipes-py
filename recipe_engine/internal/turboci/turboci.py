# Copyright 2026 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Real client to the TurboCI Orchestrator service."""

import logging
import sys

from gevent import subprocess

from google.protobuf import json_format as jsonpb

from PB.turboci.graph.orchestrator.v1.query_nodes_request import QueryNodesRequest
from PB.turboci.graph.orchestrator.v1.query_nodes_response import QueryNodesResponse
from PB.turboci.graph.orchestrator.v1.read_workplan_request import ReadWorkPlanRequest
from PB.turboci.graph.orchestrator.v1.read_workplan_response import ReadWorkPlanResponse
from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest
from PB.turboci.graph.orchestrator.v1.write_nodes_response import WriteNodesResponse

from .common import TurboCIClient

LOG = logging.getLogger(__name__)
TURBOCI = 'turboci.exe' if sys.platform == 'win32' else 'turboci'


class TurboCIOrchestrator(TurboCIClient):

  def __init__(self, endpoint: str):
    super().__init__()
    self.endpoint = endpoint

  def WriteNodes(self, req: WriteNodesRequest) -> WriteNodesResponse:
    LOG.info('write-nodes request: %s', jsonpb.MessageToJson(req))
    ret = self._run_cmd('write-nodes', req.SerializeToString())
    res = WriteNodesResponse()
    res.ParseFromString(ret)
    LOG.info('write-nodes response: %s', jsonpb.MessageToJson(res))
    return res

  def QueryNodes(self, req: QueryNodesRequest) -> QueryNodesResponse:
    LOG.info('query-nodes request: %s', jsonpb.MessageToJson(req))
    ret = self._run_cmd('query-nodes', req.SerializeToString())
    res = QueryNodesResponse()
    res.ParseFromString(ret)
    LOG.info('query-nodes response: %s', jsonpb.MessageToJson(res))
    return res

  def ReadWorkPlan(self, req: ReadWorkPlanRequest) -> ReadWorkPlanResponse:
    LOG.info('read-workplan request: %s', jsonpb.MessageToJson(req))
    ret = self._run_cmd('read-workplan', req.SerializeToString())
    res = ReadWorkPlanResponse()
    res.ParseFromString(ret)
    LOG.info('read-workplan response: %s', jsonpb.MessageToJson(res))
    return res

  def _run_cmd(self, sub_cmd: str, req: bytes) -> bytes:
    cmd = [TURBOCI, sub_cmd, '--endpoint', self.endpoint]

    try:
      proc = subprocess.run(cmd, input=req, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
      LOG.error('failed with retcode %d', e.returncode)
      LOG.error('stderr: %s', e.stderr)
      raise
    return proc.stdout
