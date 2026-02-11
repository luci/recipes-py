#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf.struct_pb2 import Struct, Value
from google.protobuf.timestamp_pb2 import Timestamp

import test_env

import turboci_test_helper

from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.query import Query

from recipe_engine import turboci

demoStruct = Struct(fields={'hello': Value(string_value='world')})
demoStruct2 = Struct(fields={'hola': Value(string_value='mundo')})

demoTS = Timestamp(seconds=100, nanos=100)
demoTS2 = Timestamp(seconds=200, nanos=200)


class TransactionTest(turboci_test_helper.TestBaseClass):

  def test_simple_transaction(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNING',
        ))

    def _mutate(txn: turboci.Transaction):
      rslt = txn.read_checks("hey")[0]
      if not rslt.options:
        txn.write_nodes(
            turboci.check("hey", options=[demoStruct, demoTS]),
            turboci.reason('I feel like it'),
        )

    self.run_transaction(_mutate)

    rslt = self.read_checks(
        'hey',
        collect=Query.CollectChecks(options=True),
        types=[demoStruct, demoTS])[0]
    self.assertEqual(len(rslt.options), 2)

  def test_transaction_retry(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNING',
        ))

    first_attempt = [True]

    def _mutate(txn: turboci.Transaction):
      # This includes the check 'hey' in the transaction and starts the
      # snapshot.
      txn.read_checks("hey")

      # DO NOT DO THIS vvvv: NEVER DIRECTLY INTERACT WITH THE DB IN A TRANSACTION.
      if first_attempt[0]:
        first_attempt[0] = False
        self.write_nodes(
            turboci.reason('sneaky write'),
            turboci.check('hey', options=[demoStruct2]),
        )
        # After this, our `write` should raise a transaction failure error, but
        # the next transaction attempt should succeed.
      # DO NOT DO THIS ^^^^

      txn.write_nodes(
          turboci.reason('transactional write'),
          turboci.check("hey", options=[demoTS]),
      )

    self.run_transaction(_mutate)

    self.assertFalse(first_attempt[0])

    rslt = self.read_checks(
        'hey',
        collect=Query.CollectChecks(options=True),
        types=[demoStruct2, demoTS])[0]
    # We should have both data types in Struct, TS order.
    self.assertEqual(len(rslt.options), 2)
    self.assertEqual(rslt.options[0].value.value.type_url,
                     turboci.type_url_for(demoStruct2))
    self.assertEqual(rslt.options[1].value.value.type_url,
                     turboci.type_url_for(demoTS))

  def test_transactional_creation(self):
    first_attempt = [True]

    def _mutate(txn: turboci.Transaction):
      if not txn.read_checks('hey'):
        # does not already exist - write a new node kind which obviously
        # conflicts with the sneaky write. Having a dynamic kind like this for
        # real is certainly an error.
        delta = turboci.check('hey', kind='CHECK_KIND_BUILD')
      else:
        # The check already exists, add an option to it, regardless of kind.
        delta = turboci.check('hey', options=[demoStruct])

      # DO NOT DO THIS vvvv: NEVER DIRECTLY INTERACT WITH THE DB IN A TRANSACTION.
      if first_attempt[0]:
        first_attempt[0] = False
        self.write_nodes(
            turboci.reason('sneaky write'),
            turboci.check('hey', kind='CHECK_KIND_ANALYSIS'),
        )
        # After this, our `write` should raise a transaction failure error, but
        # the next transaction attempt should succeed.
      # DO NOT DO THIS ^^^^

      txn.write_nodes(turboci.reason('transactional write'), delta)

    self.run_transaction(_mutate)

    self.assertFalse(first_attempt[0])

    rslt = self.read_checks(
        'hey', collect=Query.CollectChecks(options=True), types=[demoStruct])[0]
    # Since we only conditionally wrote, we see the kind written outside
    # the transaction but the option written by the transaction.
    self.assertEqual(rslt.kind, CheckKind.CHECK_KIND_ANALYSIS)
    self.assertEqual(rslt.options[0].value.value.type_url,
                     turboci.type_url_for(demoStruct))


if __name__ == '__main__':
  test_env.main()
