# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Real client to the TurboCI Orchestrator service."""

import logging
import sys

from gevent import subprocess

from google.protobuf import json_format as jsonpb
from google.protobuf.message import Message

from PB.turboci.graph.orchestrator.v1.query_nodes_request import (
    QueryNodesRequest,
)
from PB.turboci.graph.orchestrator.v1.query_nodes_response import (
    QueryNodesResponse,
)
from PB.turboci.graph.orchestrator.v1.read_workplan_request import (
    ReadWorkPlanRequest,
)
from PB.turboci.graph.orchestrator.v1.read_workplan_response import (
    ReadWorkPlanResponse,
)
from PB.turboci.graph.orchestrator.v1.write_nodes_request import (
    WriteNodesRequest,
)
from PB.turboci.graph.orchestrator.v1.write_nodes_response import (
    WriteNodesResponse,
)

from .common import TurboCIClient
from . import query_util

LOG = logging.getLogger(__name__)
TURBOCI = 'turboci.exe' if sys.platform == 'win32' else 'turboci'


class TurboCIOrchestrator(TurboCIClient):

  def __init__(self, endpoint: str):
    super().__init__()
    self.endpoint = endpoint

  def WriteNodes(self, req: WriteNodesRequest) -> WriteNodesResponse:
    self._log_request('write-nodes', req)
    ret = self._run_cmd('write-nodes', req.SerializeToString())
    res = WriteNodesResponse()
    res.ParseFromString(ret)
    LOG.info('write-nodes response: %s', jsonpb.MessageToJson(res))
    return res

  def QueryNodes(self, req: QueryNodesRequest) -> QueryNodesResponse:
    self._log_request('query-nodes', req)
    # Calls ReadWorkPlan under the hood, with some limitations:
    # * Currently only supports the case where all queries are searching the
    # same Workplan.
    # * The checks will only be included in the result if the query-nodes
    # request specifies both `select_checks` and `collect_checks`.
    # * Stages and edits are not supported for now, just like the fake.
    # TODO(b/460826158): call `query-nodes` directly after QueryNodes is ready
    # at the server side.
    read_req = query_util.query_to_read_work_plan_request(req)
    read_response = self._read_work_plan(read_req)
    res = query_util.filter_read_work_plan_responses(req, read_response)
    LOG.info('query-nodes response: %s', jsonpb.MessageToJson(res))
    return res

  def ReadWorkPlan(self, req: ReadWorkPlanRequest) -> ReadWorkPlanResponse:
    self._log_request('read-workplan', req)
    ret = self._run_cmd('read-workplan', req.SerializeToString())
    res = ReadWorkPlanResponse()
    res.ParseFromString(ret)
    LOG.info('read-workplan response: %s', jsonpb.MessageToJson(res))
    return res

  def _read_work_plan(self, req: ReadWorkPlanRequest) -> ReadWorkPlanResponse:
    return query_util.paginate_read_work_plan(self.ReadWorkPlan, req)

  def _run_cmd(self, sub_cmd: str, req: bytes) -> bytes:
    cmd = [TURBOCI, sub_cmd, '--endpoint', self.endpoint]

    try:
      proc = subprocess.run(cmd, input=req, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
      LOG.error('failed with retcode %d', e.returncode)
      LOG.error('stderr: %s', e.stderr)
      raise
    return proc.stdout

  def _log_request(self, name: str, req: Message):
    """Redacts token and logs the request."""
    req_copy = req.__class__()
    req_copy.CopyFrom(req)
    if hasattr(req_copy, 'token') and req_copy.token:
      req_copy.token = '<redacted>'
    LOG.info('%s request: %s', name, jsonpb.MessageToJson(req_copy))
