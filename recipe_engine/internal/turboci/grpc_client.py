# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Real cooperative gRPC client to the TurboCI Orchestrator service."""

from __future__ import annotations

from gevent.threadpool import ThreadPool
import json
import logging
import random
import threading
import time
import urllib.request

import grpc
from google.protobuf import json_format as jsonpb
from google.protobuf import message as protobuf_message
from google.rpc import code_pb2

from turboci.utils.client import clients, errors, transports
from turboci.utils.client import grpc_transport
from recipe_engine.third_party import luci_context

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.query_nodes_request import (
    QueryNodesRequest,)
from PB.turboci.graph.orchestrator.v1.query_nodes_response import (
    QueryNodesResponse,)
from PB.turboci.graph.orchestrator.v1.read_workplan_request import (
    ReadWorkPlanRequest,)
from PB.turboci.graph.orchestrator.v1.read_workplan_response import (
    ReadWorkPlanResponse,)
from PB.turboci.graph.orchestrator.v1.write_nodes_request import (
    WriteNodesRequest,)
from PB.turboci.graph.orchestrator.v1.write_nodes_response import (
    WriteNodesResponse,)

from . import query_util

LOG = logging.getLogger(__name__)

_DEFAULT_MAX_CONCURRENT_RPCS = 10


class _LocalAuthTokenManager:
  """Manages and caches OAuth access tokens from LUCI_CONTEXT.

  Because the client is multiplexed as a shared process-lifetime singleton
  across hundreds of recipe build steps over multi-hour executions, static
  token fetching without active expiration tracking causes long-running
  builds to fail abruptly with `UNAUTHENTICATED` errors after 1 hour.
  """

  def __init__(self):
    self._token_cache: tuple[str, float | None] | None = None
    self._token_lock = threading.Lock()

    local_auth = luci_context.read("local_auth") or {}
    self._default_account_id: str | None = local_auth.get("default_account_id")
    self._secret: str | None = local_auth.get("secret")
    self._local_auth_url: str | None = None
    if raw_port := local_auth.get("rpc_port"):
      port = int(raw_port)
      self._local_auth_url = (
          f"http://127.0.0.1:{port}/rpc/LuciLocalAuthService.GetOAuthToken")

  def _is_cache_valid(self, cache: tuple[str, float | None] | None) -> bool:
    if cache is None:
      return False
    _, expiry = cache
    if expiry is None:
      return True
    jitter = random.uniform(60.0, 120.0)
    return (expiry - time.time()) > jitter

  def get_token(self) -> str | None:
    """Extracts and caches an OAuth access token from LUCI_CONTEXT."""
    # Fast-path check without acquiring the lock.
    cache = self._token_cache
    if self._is_cache_valid(cache):
      return cache[0]

    if not self._local_auth_url:
      return None

    with self._token_lock:
      # Double-check after acquiring the lock in case another greenlet/thread
      # refreshed the token while we were waiting.
      if self._is_cache_valid(self._token_cache):
        return self._token_cache[0]

      try:
        payload = {
            "scopes": ["https://www.googleapis.com/auth/userinfo.email"],
        }
        if self._default_account_id:
          payload["account_id"] = self._default_account_id
        if self._secret:
          payload["secret"] = self._secret

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._local_auth_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
          token_resp = json.loads(resp.read().decode("utf-8"))
          error_code = token_resp.get("error_code")
          if error_code:
            LOG.warning(
                "LuciLocalAuthService.GetOAuthToken returned error %s: %s",
                error_code,
                token_resp.get("error_message", "unknown error"),
            )
            return None
          access_token = token_resp.get("access_token")
          if not access_token:
            return None
          expiry = token_resp.get("expiry")
          expiry_val = float(expiry) if expiry is not None else None
          self._token_cache = (str(access_token), expiry_val)
          return str(access_token)
      except Exception as e:
        LOG.warning("Failed to retrieve OAuth token from LUCI_CONTEXT: %s", e)
        return None


def _init_grpc_channel(endpoint: str) -> grpc.Channel:
  """Constructs an expiration-aware, self-retrying secure gRPC channel.

  Embeds a JSON service configuration directly into channel initialization
  to enable native HTTP/2 exponential backoff retries for retriable errors.
  """
  options = [
      ("grpc.service_config",
       json.dumps({
           "methodConfig": [{
               "name": [{
                   "service":
                       ("turboci.graph.orchestrator.v1.TurboCIOrchestrator")
               }],
               "waitForReady": True,
               "retryPolicy": {
                   "maxAttempts":
                       5,
                   "initialBackoff":
                       "0.01s",
                   "maxBackoff":
                       "1.0s",
                   "backoffMultiplier":
                       2.0,
                   "retryableStatusCodes": [
                       code_pb2.Code.Name(code)
                       for code in errors.RETRYABLE_RPC_CODES
                   ],
               },
           }]
       })),
      ("grpc.primary_user_agent", "turboci-recipe-engine/gRPC-client"),
  ]

  if endpoint.startswith(("localhost", "127.0.0.1", "[::1]")):
    return grpc.insecure_channel(endpoint, options=options)

  token_manager = _LocalAuthTokenManager()

  # Callback invoked by gRPC's C-core on every outgoing request to inject
  # the current OAuth Bearer token into HTTP/2 metadata headers.
  def auth_metadata_plugin(context, callback):
    token = token_manager.get_token()
    if token:
      callback([("authorization", f"Bearer {token}")], None)
    else:
      callback([], None)

  # Enable TLS/SSL transport layer security using system root CA certs.
  ssl_creds = grpc.ssl_channel_credentials()
  # Wrap the OAuth header plugin into gRPC call credentials.
  auth_creds = grpc.metadata_call_credentials(auth_metadata_plugin)
  # Merge TLS transport encryption and OAuth call credentials to ensure
  # secret tokens are transmitted exclusively over encrypted TLS streams.
  combined_creds = grpc.composite_channel_credentials(ssl_creds, auth_creds)
  return grpc.secure_channel(endpoint, combined_creds, options=options)


class _RecipeGrpcTransport(grpc_transport.GrpcTransport):
  """gRPC transport with request/response logging and QueryNodes emulation."""

  def __init__(
      self,
      channel: grpc.Channel,
      max_concurrency: int = _DEFAULT_MAX_CONCURRENT_RPCS,
  ):
    super().__init__(channel)
    # Dedicated thread pool bounded to at most `max_concurrency` gevent threads.
    self._thread_pool = ThreadPool(maxsize=max_concurrency)

  def call_unary(
      self,
      method_name: str,
      request: protobuf_message.Message,
      options: transports.CallOptions | None = None,
  ) -> protobuf_message.Message:
    self._log_request(method_name, request)
    if method_name == "QueryNodes":
      res = self._query_nodes(request, options=options)
    else:
      res = self._call_unary_in_thread(method_name, request, options=options)
    self._log_response(method_name, res)
    return res

  def _call_unary_in_thread(
      self,
      method_name: str,
      request: protobuf_message.Message,
      options: transports.CallOptions | None = None,
  ) -> protobuf_message.Message:
    """Offloads the blocking gRPC C-call to gevent's background threadpool."""
    return self._thread_pool.spawn(
        super().call_unary, method_name, request, options=options
    ).get()

  def _query_nodes(
      self,
      req: QueryNodesRequest,
      options: transports.CallOptions | None = None,
  ) -> QueryNodesResponse:
    read_req = query_util.query_to_read_work_plan_request(req)
    read_response = self._read_work_plan(read_req, options=options)
    return query_util.filter_read_work_plan_responses(req, read_response)

  def _read_work_plan(
      self,
      req: ReadWorkPlanRequest,
      options: transports.CallOptions | None = None,
  ) -> ReadWorkPlanResponse:
    return query_util.paginate_read_work_plan(
        lambda r: self._call_unary_in_thread(
            "ReadWorkPlan", r, options=options),
        req,
    )

  def _log_request(self, name: str, req: protobuf_message.Message):
    req_copy = req.__class__()
    req_copy.CopyFrom(req)
    if hasattr(req_copy, "token") and req_copy.token:
      req_copy.token = "<redacted>"
    LOG.info("%s request: %s", name, jsonpb.MessageToJson(req_copy))

  def _log_response(self, name: str, res: protobuf_message.Message):
    LOG.info("%s response: %s", name, jsonpb.MessageToJson(res))


def TurboCIGRPCClient(
    endpoint: str,
    wpid: identifier.WorkPlan,
    token: str | None = None,
    logger: logging.Logger | None = None,
) -> clients.Sync:
  """Constructs a synchronous TurboCI client over cooperative gRPC."""
  channel = _init_grpc_channel(endpoint)
  transport = _RecipeGrpcTransport(channel)
  return clients.Sync(
      transport=transport,
      wpid=wpid,
      token=token,
      logger=logger or LOG,
  )
