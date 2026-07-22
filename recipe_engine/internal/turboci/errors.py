# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from google.rpc import code_pb2
from turboci.utils import client


def InvalidArgumentException(msg: str) -> client.RPCError:
  return client.RPCError.make(msg, code=code_pb2.INVALID_ARGUMENT)
