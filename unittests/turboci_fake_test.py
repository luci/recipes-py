#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import test_env
import turboci_test_helper

from google.protobuf.message import Message
from google.protobuf.any_pb2 import Any
from google.protobuf.timestamp_pb2 import Timestamp
from google.protobuf.struct_pb2 import ListValue, Struct, Value

from PB.turboci.graph.ids.v1 import identifier
from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_kind import CheckKind
from PB.turboci.graph.orchestrator.v1.check_state import CheckState
from PB.turboci.graph.orchestrator.v1.datum import Datum
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.edge_group import EdgeGroup
from PB.turboci.graph.orchestrator.v1.query import Query
from PB.turboci.graph.orchestrator.v1.revision import Revision

from recipe_engine import turboci
from recipe_engine.internal.turboci.common import check_id
from recipe_engine.internal.turboci.fake import _IndexEntrySnapshot
from recipe_engine.internal.turboci.ids import AnyIdentifier, type_url_for, type_urls

demoStruct = Struct(fields={'hello': Value(string_value='world')})
demoStruct2 = Struct(fields={'hola': Value(string_value='mundo')})

demoTS = Timestamp(seconds=100, nanos=100)
demoTS2 = Timestamp(seconds=200, nanos=200)

structURL = type_url_for(demoStruct)
tsURL = type_url_for(demoTS)


def _mkAny(value: Message) -> Any:
  ret = Any()
  ret.Pack(value, deterministic=True)
  return ret


def _mkDatum(ident: AnyIdentifier, value: Message, version: Revision) -> Datum:
  ret = Datum(identifier=turboci.wrap_id(ident), version=version)
  ret.value.value.Pack(value, deterministic=True)
  return ret


def _mkOptions(id: str,
               *msg: type[Message] | Message,
               in_workplan: str = "") -> list[Check.OptionRef]:
  ident = check_id(id, in_workplan=in_workplan)
  return [
      Check.OptionRef(
          type_url=turboci.type_url_for(m),
          identifier=identifier.CheckOption(check=ident, idx=i + 1))
      for i, m in enumerate(msg)
  ]


def _mkResults(id: str,
               *msg: type[Message] | Message,
               in_workplan: str = "",
               result_idx: int = 1) -> list[Check.Result.ResultDatumRef]:
  ident = check_id(id, in_workplan=in_workplan)
  return [
      Check.Result.ResultDatumRef(
          type_url=turboci.type_url_for(m),
          identifier=identifier.CheckResultDatum(
              result=identifier.CheckResult(check=ident, idx=result_idx),
              idx=i + 1,
          )) for i, m in enumerate(msg)
  ]


class IndexEntrySnapshotTest(test_env.RecipeEngineUnitTest):

  def test_snapshot(self):
    ident = check_id('thing')
    deps = [
        turboci.edge_group('a', 'b'),
    ]
    deps[0].edges[1].resolution.satisfied = True
    check = Check(
        identifier=ident,
        kind='CHECK_KIND_TEST',
        state='CHECK_STATE_WAITING',
        options=_mkOptions('thing', Struct, Value, ListValue),
        results=[
            Check.Result(data=_mkResults('thing', Struct, Value),),
        ],
        dependencies=deps,
    )
    entry = _IndexEntrySnapshot.for_check(check)
    self.assertEqual(entry.kind, CheckKind.CHECK_KIND_TEST)
    self.assertEqual(entry.state, CheckState.CHECK_STATE_WAITING)
    self.assertEqual(
        entry.option_types, {
            'type.googleapis.com/google.protobuf.Struct',
            'type.googleapis.com/google.protobuf.Value',
            'type.googleapis.com/google.protobuf.ListValue',
        })
    self.assertEqual(
        entry.result_types, {
            'type.googleapis.com/google.protobuf.Struct',
            'type.googleapis.com/google.protobuf.Value',
        })
    self.assertEqual(entry.deps, {('L:Ca', None), ('L:Cb', True)})

  def test_empty_snapshot(self):
    entry = _IndexEntrySnapshot.for_check(None)
    self.assertEqual(entry.kind, 0)
    self.assertEqual(entry.state, 0)
    self.assertEqual(entry.option_types, set())
    self.assertEqual(entry.result_types, set())
    self.assertEqual(entry.deps, set())


class SimpleTurboCIFakeTest(turboci_test_helper.TestBaseClass):
  def test_single_check_write(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))

    rslt = self.query_nodes(
        turboci.make_query(
            Query.Select(nodes=turboci.collect_check_ids('hey')),
            Query.Collect.Check(options=True),
            types=[demoStruct],
        ))[""]
    self.assertEqual(len(rslt.checks), 1)
    self.assertEqual(
        rslt.checks['hey'].check,
        Check(
            identifier=turboci.check_id('hey'),
            state='CHECK_STATE_PLANNING',
            kind='CHECK_KIND_BUILD',
            version=rslt.version,
            options=_mkOptions('hey', demoStruct),
        ))
    self.assertEqual(
        rslt.checks['hey'].option_data[structURL],
        _mkDatum(
            turboci.wrap_id(rslt.checks['hey'].check.options[0].identifier),
            demoStruct,
            rslt.version,
        ))

  def test_check_state_PLANNING_add_option(self):
    self.write_nodes(turboci.check(
        'hey',
        kind='CHECK_KIND_BUILD',
    ))
    self.write_nodes(turboci.check(
        'hey',
        options=[demoStruct],
    ))
    rslt = self.read_checks(
        'hey',
        collect=Query.Collect.Check(options=True),
        types=[Struct],
    )[0]
    self.assertEqual(rslt.option_data[structURL].value.value, _mkAny(demoStruct))

  def test_check_state_PLANNING_overwrite_option(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    self.write_nodes(turboci.check(
        'hey',
        options=[demoStruct2],
    ))
    rslt = self.read_checks(
        'hey',
        collect=Query.Collect.Check(options=True),
        types=[Struct],
    )[0]
    self.assertEqual(rslt.option_data[structURL].value.value, _mkAny(demoStruct2))

  def test_check_state_PLANNING_add_second_option(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    self.write_nodes(turboci.check(
        'hey',
        options=[demoTS],
    ))
    rslt = self.read_checks(
        'hey',
        collect=Query.Collect.Check(options=True),
        types=[Struct, Timestamp],
    )[0]
    self.assertEqual(rslt.option_data[structURL].value.value, _mkAny(demoStruct))
    self.assertEqual(rslt.option_data[tsURL].value.value, _mkAny(demoTS))

  def test_check_state_PLANNING_add_dependency(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            # Note: we can add a dependency to a check which we are writing
            # concurrently with 'hey'.
            deps=[turboci.edge_group('there')],
        ),
        turboci.check(
            'there',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(len(rslt.check.dependencies), 1)
    self.assertEqual(
        rslt.check.dependencies[0],
        EdgeGroup(edges=[Edge(target=turboci.wrap_id(check_id('there')))]))

  def test_error_check_state_missing_dep(self):
    with self.assertRaisesRegex(turboci.InvalidArgumentException,
                                "unsatisfiable dependencies"):
      self.write_nodes(
          turboci.check(
              'hey',
              kind='CHECK_KIND_BUILD',
              deps=[turboci.edge_group('missing')],
          ))

  def test_check_state_PLANNING_replace_dependency(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            # Note: we can add a dependency to a check which we are writing
            # concurrently with 'hey'.
            deps=[turboci.edge_group('there')],
        ),
        turboci.check(
            'there',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    self.write_nodes(
        turboci.check(
            'hey',
            deps=[turboci.edge_group('there', 'moo')],
        ), turboci.check(
            'moo',
            kind='CHECK_KIND_BUILD',
        ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(len(rslt.check.dependencies), 1)
    self.assertEqual(rslt.check.dependencies[0],
                     turboci.edge_group('there', 'moo'))

  def test_check_state_PLANNING_evolve(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    # update options and mark PLANNED
    self.write_nodes(
        turboci.check(
            'hey',
            options=[demoStruct2],
            state='CHECK_STATE_PLANNED',
        ))
    with self.assertRaises(turboci.CheckWriteInvariantException):
      # Can't write options any more
      self.write_nodes(turboci.check(
          'hey',
          options=[demoTS],
      ))
    rslt = self.read_checks('hey')[0]
    # This had no dependencies so goes straight to WAITING.
    self.assertEqual(rslt.check.state, CheckState.CHECK_STATE_WAITING)

  def test_check_state_PLANNED_start(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            state='CHECK_STATE_PLANNED',
        ))
    with self.assertRaises(turboci.CheckWriteInvariantException):
      # Can't write options any more
      self.write_nodes(turboci.check(
          'hey',
          options=[demoStruct2],
      ))

    rslt = self.read_checks('hey')[0]
    # This had no dependencies so goes straight to WAITING.
    self.assertEqual(rslt.check.state, CheckState.CHECK_STATE_WAITING)

  def test_check_state_PLANNED_with_deps(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            # Note: we can add a dependency to a check which we are writing
            # concurrently with 'hey'.
            deps=[turboci.edge_group('there')],
        ),
        turboci.check(
            'there',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    self.write_nodes(turboci.check(
        'hey',
        state='CHECK_STATE_PLANNED',
    ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(rslt.check.state, CheckState.CHECK_STATE_PLANNED)

    # completing `there` unblocks `hey`.
    self.write_nodes(turboci.check(
        'there',
        state='CHECK_STATE_FINAL',
    ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(rslt.check.state, CheckState.CHECK_STATE_WAITING)

  def test_check_linear_chain(self):
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_BUILD',
            deps=[turboci.edge_group('b')],
        ),
        turboci.check(
            'b',
            kind='CHECK_KIND_BUILD',
            deps=[turboci.edge_group('c')],
        ), turboci.check(
            'c',
            kind='CHECK_KIND_BUILD',
        ))
    ret = self.read_checks('a')[0]
    self.assertEqual(ret.check.state, CheckState.CHECK_STATE_PLANNING)

    self.write_nodes(
        turboci.check(
            'a',
            state='CHECK_STATE_PLANNED',
        ), turboci.check(
            'b',
            state='CHECK_STATE_PLANNED',
        ))

    ret = self.read_checks('a')[0]
    self.assertEqual(ret.check.state, CheckState.CHECK_STATE_PLANNED)

    self.write_nodes(turboci.check(
        'c',
        state='CHECK_STATE_FINAL',
    ))

    ret = self.read_checks('b')[0]
    self.assertEqual(ret.check.state, CheckState.CHECK_STATE_WAITING)

    self.write_nodes(turboci.check(
        'b',
        state='CHECK_STATE_FINAL',
    ))

    ret = self.read_checks('a')[0]
    self.assertEqual(ret.check.state, CheckState.CHECK_STATE_WAITING)

  def test_check_add_dep_to_FINAL(self):
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_BUILD',
        ),
        turboci.check(
            'b',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_FINAL',
        ))
    ret = self.read_checks('a')[0]
    self.assertEqual(ret.check.state, CheckState.CHECK_STATE_PLANNING)

    self.write_nodes(
        turboci.check(
            'a',
            state='CHECK_STATE_PLANNED',
            deps=[turboci.edge_group('b')],
        ))
    ret = self.read_checks('a')[0]
    self.assertEqual(ret.check.state, CheckState.CHECK_STATE_WAITING)

  def test_check_PLANNING_to_FINAL(self):
    self.write_nodes(turboci.check(
        'hey',
        kind='CHECK_KIND_BUILD',
    ))
    # You can go directly from PLANNING->FINAL if there are no unresolved
    # dependencies.
    self.write_nodes(
        turboci.check(
            'hey',
            state='CHECK_STATE_FINAL',
            results=[demoStruct],
        ))
    rslt = self.read_checks(
        'hey',
        collect=Query.Collect.Check(options=True, result_data=True),
        types=[demoStruct],
    )[0]
    self.assertEqual(rslt.check.state, CheckState.CHECK_STATE_FINAL)
    self.assertEqual(rslt.check.results[0].data[0].type_url,
                     turboci.type_url_for(demoStruct))
    self.assertTrue(rslt.check.results[0].HasField('created_at'))
    self.assertTrue(rslt.check.results[0].HasField('finalized_at'))
    self.assertEqual(rslt.results[1].data[structURL].value.value, _mkAny(demoStruct))

  def test_check_WAITING_results(self):
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            state=CheckState.CHECK_STATE_WAITING,
        ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(rslt.check.state, CheckState.CHECK_STATE_WAITING)

    self.write_nodes(turboci.check(
        'hey',
        results=[demoStruct],
    ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(rslt.check.results[0].data[0].type_url,
                     turboci.type_url_for(demoStruct))

    self.assertTrue(rslt.check.results[0].HasField('created_at'))
    created_ts = rslt.check.results[0].created_at
    self.assertFalse(rslt.check.results[0].HasField('finalized_at'))

    self.write_nodes(turboci.check(
        'hey',
        finalize_results=True,
    ))
    rslt = self.read_checks('hey')[0]
    self.assertTrue(rslt.check.results[0].HasField('finalized_at'))
    finalized_ts = rslt.check.results[0].finalized_at

    self.assertGreater((finalized_ts.ts.seconds, finalized_ts.ts.nanos),
                       (created_ts.ts.seconds, created_ts.ts.nanos))

  def test_query_filter_kind(self):
    self.write_nodes(
        turboci.check('a', kind='CHECK_KIND_ANALYSIS'),
        turboci.check('b', kind='CHECK_KIND_SOURCE'),
        turboci.check('c', kind='CHECK_KIND_BUILD'),
        turboci.check('cc', kind='CHECK_KIND_BUILD'),
    )

    ret = self.query_nodes(
        turboci.make_query(
            Query.Select.CheckPattern(kind='CHECK_KIND_ANALYSIS'),
            Query.Select.CheckPattern(kind=CheckKind.CHECK_KIND_BUILD),
        ))[""]
    self.assertEqual(len(ret.checks), 3)
    self.assertEqual(set(ret.checks), {'a', 'c', 'cc'})

  def test_query_filter_option(self):
    self.write_nodes(
        turboci.check('a', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
        turboci.check(
            'b', kind='CHECK_KIND_ANALYSIS', options=[demoTS]),
        turboci.check(
            'c', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
    )

    ret = self.query_nodes(
        turboci.make_query(
            Query.Select.CheckPattern(
                with_option_types=turboci.type_urls(demoStruct)),))[""]
    self.assertEqual(len(ret.checks), 2)
    self.assertEqual(set(ret.checks), {'a', 'c'})

  def test_query_filter_all_options(self):
    self.write_nodes(
        turboci.check('a', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
        turboci.check('b', kind='CHECK_KIND_ANALYSIS', options=[demoTS]),
        turboci.check('c', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
    )

    ret = self.query_nodes(turboci.make_query(
        Query.Select.CheckPattern(),
        Query.Collect.Check(options=True),
        types=('*',),
    ))[""]
    self.assertEqual(len(ret.checks), 3)
    self.assertEqual(set(ret.checks), {'a', 'b', 'c'})
    types = set()
    for check in ret.checks.values():
      types.update(check.option_data)
    self.assertEqual(types, set(type_urls(demoStruct, demoTS)))


  def test_query_filter_result(self):
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_ANALYSIS',
            results=[demoStruct],
            state='CHECK_STATE_FINAL'),
        turboci.check(
            'b',
            kind='CHECK_KIND_ANALYSIS',
            results=[demoTS],
            state='CHECK_STATE_FINAL'),
        turboci.check(
            'c',
            kind='CHECK_KIND_ANALYSIS',
            results=[demoStruct],
            state='CHECK_STATE_FINAL'),
    )

    ret = self.query_nodes(
        turboci.make_query(
            Query.Select.CheckPattern(
                with_result_data_types=turboci.type_urls(demoStruct)),))[""]

    self.assertEqual(len(ret.checks), 2)
    self.assertEqual(set(ret.checks), {'a', 'c'})

  def test_query_filter_id_regex(self):
    self.write_nodes(
        turboci.check('a/b/c', kind='CHECK_KIND_ANALYSIS'),
        turboci.check('butter', kind='CHECK_KIND_SOURCE'),
        turboci.check('clorp', kind='CHECK_KIND_BUILD'),
        turboci.check('neat', kind='CHECK_KIND_BUILD'),
    )

    ret = self.query_nodes(
        turboci.make_query(Query.Select.CheckPattern(id_regex='.*[er].*'),))[""]
    self.assertEqual(len(ret.checks), 3)
    self.assertEqual(set(ret.checks), {'clorp', 'butter', 'neat'})

  def test_query_filter_follow_down(self):
    # make a simple diamond
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_ANALYSIS',
            deps=[turboci.edge_group('b', 'c')],
        ),
        turboci.check(
            'b',
            kind='CHECK_KIND_TEST',
            deps=[turboci.edge_group('d')],
        ),
        turboci.check(
            'c',
            kind='CHECK_KIND_TEST',
            deps=[turboci.edge_group('d')],
        ),
        turboci.check(
            'd',
            kind='CHECK_KIND_BUILD',
            deps=[turboci.edge_group('s')],
        ),
        turboci.check(
            's',
            kind='CHECK_KIND_SOURCE',
            state='CHECK_STATE_FINAL',
        ))

    ret = self.query_nodes(
        turboci.make_query(
            Query.Select.CheckPattern(kind='CHECK_KIND_ANALYSIS'),
            Query.Expand.Dependencies(dependencies_depth=2),
        ))[""]
    self.assertEqual(len(ret.checks), 4)
    self.assertEqual(set(ret.checks), {'a', 'b', 'c', 'd'})

  def test_query_filter_follow_up(self):
    # make a simple diamond
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_ANALYSIS',
            deps=[turboci.edge_group('b', 'c')],
        ),
        turboci.check(
            'b',
            kind='CHECK_KIND_TEST',
            deps=[turboci.edge_group('d')],
        ),
        turboci.check(
            'c',
            kind='CHECK_KIND_TEST',
            deps=[turboci.edge_group('d')],
        ),
        turboci.check(
            'd',
            kind='CHECK_KIND_BUILD',
            deps=[turboci.edge_group('s')],
        ),
        turboci.check(
            's',
            kind='CHECK_KIND_SOURCE',
            state='CHECK_STATE_FINAL',
        ))

    ret = self.query_nodes(
        turboci.make_query(
            Query.Select.CheckPattern(kind=CheckKind.CHECK_KIND_SOURCE),
            Query.Expand.Dependencies(dependents_depth=2),
        ))[""]
    self.assertEqual(len(ret.checks), 4)
    self.assertEqual(set(ret.checks), {'s', 'b', 'c', 'd'})


if __name__ == '__main__':
  test_env.main()
