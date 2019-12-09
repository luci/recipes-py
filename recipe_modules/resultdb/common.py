# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import test_result as test_result_pb2

# Kinds of items in an invocation.
# A tuple of (property, protobufType), where property is a name of a JSON
# object property used in `rdb ls` and `rdb chromium-derve` subcommands.
# See _parse_query_output in api.py
KINDS = (
  ('testResult', test_result_pb2.TestResult),
  ('testExoneration', test_result_pb2.TestExoneration),
)

# Maps a protobuf type to a property name.
KINDS_REVERSE = {t: k for (k, t) in KINDS}
