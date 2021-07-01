# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.utils import iteritems

import json

from google.protobuf import json_format

from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2


class Invocation(object):
  """A ResultDB invocation with contents.

  Reference: go/resultdb-concepts.
  """

  # A tuple of (attr, protobuf_type, serialization_key), where
  # - attr is the name of Invocation attribute that stores the collection
  # - protobuf_type is the collection element type
  # - serialization_key: a dict key used in serialization format.
  _COLLECTIONS = (
    ('test_results', test_result_pb2.TestResult, 'testResult'),
    ('test_exonerations', test_result_pb2.TestExoneration, 'testExoneration'),
  )

  def __init__(self, proto=None, test_results=None, test_exonerations=None):
    assert proto is None or isinstance(proto, invocation_pb2.Invocation), proto
    assert _all_of_type(test_results, test_result_pb2.TestResult), test_results
    assert _all_of_type(test_exonerations, test_result_pb2.TestExoneration), (
        test_exonerations)
    self.proto = proto or invocation_pb2.Invocation()
    self.test_results = test_results or []
    self.test_exonerations = test_exonerations or []


def serialize(inv_bundle, pretty=False):
  """Serializes invocations to a string.

  The format corresponds to the format used by rdb-ls, unless pretty is True.

  Args:
    inv_bundle: dict {inv_id: Invocation}.
    pretty: if True, returns a better-looking output, but not supported by
      deserialize().
  """
  lines = []

  def add_line(inv_id, key, msg):
    jsonish = {
      'invocationId': inv_id,
      key: json_format.MessageToDict(msg),
    }
    lines.append(
        json.dumps(jsonish, sort_keys=True, indent=2 if pretty else None)
    )

  for inv_id, inv in iteritems(inv_bundle):
    assert isinstance(inv, Invocation), inv
    if inv.proto.ListFields():  # if something is set
      add_line(inv_id, 'invocation', inv.proto)

    for attr_name, typ, key in Invocation._COLLECTIONS:
      for msg in getattr(inv, attr_name):
        assert isinstance(msg, typ), msg
        add_line(inv_id, key, msg)

  return '\n'.join(lines)


def deserialize(data):
  """Deserializes an invocation bundle. Opposite of serialize()."""
  ret = {}

  def parse_msg(msg, body):
    return json_format.ParseDict(
        body, msg,
        # Do not fail the build because recipe's proto copy is stale.
        ignore_unknown_fields=True
    )

  for line in data.splitlines():
    entry = json.loads(line)
    assert isinstance(entry, dict), line

    inv_id = entry['invocationId']
    inv = ret.get(inv_id)
    if not inv:
      inv = Invocation()
      ret[inv_id] = inv

    inv_dict = entry.get('invocation')
    if inv_dict is not None:
      # Invocation is special because there can be only one invocation
      # per invocation id.
      parse_msg(inv.proto, inv_dict)
      continue

    found = False
    for attr_name, type, key in Invocation._COLLECTIONS:
      if key in entry:
        found = True
        collection = getattr(inv, attr_name)
        collection.append(parse_msg(type(), entry[key]))
        break
    assert found, entry

  return ret


def _all_of_type(lst, type):
  return not lst or all(isinstance(el, type) for el in lst)
