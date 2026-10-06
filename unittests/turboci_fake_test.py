#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import any_pb2
from google.protobuf import message
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2

import test_env
import turboci_test_helper

from PB.turboci.graph.orchestrator.v1 import check as check_pb
from PB.turboci.graph.orchestrator.v1 import check_kind as check_kind_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import dependencies as dependencies_pb
from PB.turboci.graph.orchestrator.v1 import edge as edge_pb
from PB.turboci.graph.orchestrator.v1 import query as query_pb
from PB.turboci.graph.orchestrator.v1 import value_ref as value_ref_pb
from turboci.utils import value

from recipe_engine import turboci
from recipe_engine.internal.turboci import common
from recipe_engine.internal.turboci import fake

demoStruct = struct_pb2.Struct(
    fields={'hello': struct_pb2.Value(string_value='world')})
demoStruct2 = struct_pb2.Struct(
    fields={'hola': struct_pb2.Value(string_value='mundo')})

demoTS = timestamp_pb2.Timestamp(seconds=100, nanos=100)
demoTS2 = timestamp_pb2.Timestamp(seconds=200, nanos=200)

structURL = value.url(demoStruct)
tsURL = value.url(demoTS)


def _mkAny(val: message.Message) -> any_pb2.Any:
  ret = any_pb2.Any()
  ret.Pack(val, deterministic=True)
  return ret


def _mkOptions(
    *msg: type[message.Message] | message.Message,
) -> list[value_ref_pb.ValueRef]:
  ret = []
  for m in msg:
    value_ref = value_ref_pb.ValueRef(type_url=value.url(m))
    if isinstance(m, type):
      m = m()
    value_ref.inline.Pack(m, deterministic=True)
    ret.append(value_ref)
  return ret


def _mkResults(
    *msg: type[message.Message] | message.Message,
) -> list[value_ref_pb.ValueRef]:
  ret = []
  for m in msg:
    value_ref = value_ref_pb.ValueRef(type_url=value.url(m))
    if isinstance(m, type):
      m = m()
    value_ref.inline.Pack(m, deterministic=True)
    ret.append(value_ref)
  return ret


class IndexEntrySnapshotTest(test_env.RecipeEngineUnitTest):

  def test_snapshot(self) -> None:
    ident = turboci.check_id('thing')
    check = check_pb.Check(
        identifier=ident,
        kind='CHECK_KIND_TEST',
        state='CHECK_STATE_WAITING',
        options=_mkOptions(
            struct_pb2.Struct, struct_pb2.Value, struct_pb2.ListValue),
        results=[
            check_pb.Check.Result(
                data=_mkResults(struct_pb2.Struct, struct_pb2.Value),),
        ],
    )
    entry = fake._IndexEntrySnapshot.for_check(check)
    self.assertEqual(entry.kind, check_kind_pb.CheckKind.CHECK_KIND_TEST)
    self.assertEqual(entry.state, check_state_pb.CheckState.CHECK_STATE_WAITING)
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

  def test_empty_snapshot(self) -> None:
    entry = fake._IndexEntrySnapshot.for_check(None)
    self.assertEqual(entry.kind, 0)
    self.assertEqual(entry.state, 0)
    self.assertEqual(entry.option_types, set())
    self.assertEqual(entry.result_types, set())


class SimpleTurboCIFakeTest(turboci_test_helper.TestBaseClass):
  def test_single_check_write(self) -> None:
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))

    rslt = self.query_nodes(
        turboci.make_query(
            query_pb.Query.CollectChecks(options=True),
            node_set=turboci.collect_check_ids('hey'),
        ),
        types=[demoStruct]).workplans[0]
    self.assertEqual(len(rslt.checks), 1)

    # Check that option data is correct
    check = common.get_check_by_full_id(rslt, ':Chey')
    assert check
    self.assertEqual(len(check.options), 1)

    self.assertEqual(check.options[0], value.ref(demoStruct, 'fake:realm'))

    self.assertEqual(
        check,
        check_pb.Check(
            identifier=turboci.check_id('hey'),
            state='CHECK_STATE_PLANNING',
            state_history=[
                check_pb.Check.StateHistoryEntry(
                    state='CHECK_STATE_PLANNING',
                    version=rslt.version,
                ),
            ],
            kind='CHECK_KIND_BUILD',
            realm='fake:realm',
            version=rslt.version,
            options=check.options,  # we verified contents above
            dependencies=dependencies_pb.Dependencies(),
        ))

  def test_check_state_PLANNING_add_option(self) -> None:
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
        collect=query_pb.Query.CollectChecks(options=True),
        types=[struct_pb2.Struct],
    )[0]
    self.assertEqual(len(rslt.options), 1)
    self.assertEqual(rslt.options[0].inline, _mkAny(demoStruct))

  def test_check_state_PLANNING_overwrite_option(self) -> None:
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
        collect=query_pb.Query.CollectChecks(options=True),
        types=[struct_pb2.Struct],
    )[0]
    self.assertEqual(len(rslt.options), 1)
    self.assertEqual(rslt.options[0].inline, _mkAny(demoStruct2))

  def test_check_state_PLANNING_add_second_option(self) -> None:
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
        collect=query_pb.Query.CollectChecks(options=True),
        types=[struct_pb2.Struct, timestamp_pb2.Timestamp],
    )[0]
    self.assertEqual(len(rslt.options), 2)
    # The order depends on implementation details (append), but verify existence
    vals = {o.type_url: o.inline for o in rslt.options}
    self.assertEqual(vals[structURL], _mkAny(demoStruct))
    self.assertEqual(vals[tsURL], _mkAny(demoTS))

  def test_check_state_PLANNING_add_dependency(self) -> None:
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            # Note: we can add a dependency to a check which we are writing
            # concurrently with 'hey'.
            deps=turboci.dep_group('there'),
        ),
        turboci.check(
            'there',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(len(rslt.dependencies.edges), 1)
    self.assertEqual(
        rslt.dependencies.edges[0],
        edge_pb.Edge(
            check=edge_pb.Edge.Check(identifier=turboci.check_id('there'))))

  def test_error_check_state_missing_dep(self) -> None:
    with self.assertRaisesRegex(turboci.InvalidArgumentException,
                                "unsatisfiable dependencies"):
      self.write_nodes(
          turboci.check(
              'hey',
              kind='CHECK_KIND_BUILD',
              deps=turboci.dep_group('missing'),
          ))

  def test_check_state_PLANNING_replace_dependency(self) -> None:
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            # Note: we can add a dependency to a check which we are writing
            # concurrently with 'hey'.
            deps=turboci.dep_group('there'),
        ),
        turboci.check(
            'there',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))
    self.write_nodes(
        turboci.check(
            'hey',
            deps=turboci.dep_group('there', 'moo'),
        ), turboci.check(
            'moo',
            kind='CHECK_KIND_BUILD',
        ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(len(rslt.dependencies.edges), 2)
    self.assertListEqual(
        list(rslt.dependencies.edges), [
            edge_pb.Edge(
                check=edge_pb.Edge.Check(identifier=turboci.check_id('there'))),
            edge_pb.Edge(
                check=edge_pb.Edge.Check(identifier=turboci.check_id('moo'))),
        ])
    self.assertEqual(rslt.dependencies.predicate,
                     dependencies_pb.Dependencies.Group(edges=[0, 1]))

  def test_check_state_PLANNING_evolve(self) -> None:
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
    self.assertEqual(rslt.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

  def test_check_state_PLANNED_start(self) -> None:
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
    self.assertEqual(rslt.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

  def test_check_state_PLANNED_with_deps(self) -> None:
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
            # Note: we can add a dependency to a check which we are writing
            # concurrently with 'hey'.
            deps=turboci.dep_group('there'),
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
    self.assertEqual(rslt.state, check_state_pb.CheckState.CHECK_STATE_PLANNED)

    # completing `there` unblocks `hey`.
    self.write_nodes(turboci.check(
        'there',
        state='CHECK_STATE_FINAL',
    ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(rslt.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

  def test_check_linear_chain(self) -> None:
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_BUILD',
            deps=turboci.dep_group('b'),
        ), turboci.check(
            'b',
            kind='CHECK_KIND_BUILD',
            deps=turboci.dep_group('c'),
        ), turboci.check(
            'c',
            kind='CHECK_KIND_BUILD',
        ))
    ret = self.read_checks('a')[0]
    self.assertEqual(ret.state, check_state_pb.CheckState.CHECK_STATE_PLANNING)

    self.write_nodes(
        turboci.check(
            'a',
            state='CHECK_STATE_PLANNED',
        ), turboci.check(
            'b',
            state='CHECK_STATE_PLANNED',
        ))

    ret = self.read_checks('a')[0]
    self.assertEqual(ret.state, check_state_pb.CheckState.CHECK_STATE_PLANNED)

    self.write_nodes(turboci.check(
        'c',
        state='CHECK_STATE_FINAL',
    ))

    ret = self.read_checks('b')[0]
    self.assertEqual(ret.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

    self.write_nodes(turboci.check(
        'b',
        state='CHECK_STATE_FINAL',
    ))

    ret = self.read_checks('a')[0]
    self.assertEqual(ret.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

  def test_check_add_dep_to_FINAL(self) -> None:
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
    self.assertEqual(ret.state, check_state_pb.CheckState.CHECK_STATE_PLANNING)

    self.write_nodes(
        turboci.check(
            'a',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('b'),
        ))
    ret = self.read_checks('a')[0]
    self.assertEqual(ret.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

  def test_check_PLANNING_to_FINAL(self) -> None:
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
        collect=query_pb.Query.CollectChecks(options=True, result_data=True),
        types=[demoStruct],
    )[0]
    self.assertEqual(rslt.state, check_state_pb.CheckState.CHECK_STATE_FINAL)
    self.assertEqual(rslt.results[0].data[0].type_url,
                     turboci.type_url_for(demoStruct))
    self.assertTrue(rslt.results[0].HasField('created_at'))
    self.assertTrue(rslt.results[0].HasField('finalized_at'))
    self.assertEqual(rslt.results[0].data[0].inline, _mkAny(demoStruct))

  def test_check_WAITING_results(self) -> None:
    self.write_nodes(
        turboci.check(
            'hey',
            kind='CHECK_KIND_BUILD',
            state=check_state_pb.CheckState.CHECK_STATE_WAITING,
        ))
    rslt = self.read_checks('hey')[0]
    self.assertEqual(rslt.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

    self.write_nodes(turboci.check(
        'hey',
        results=[demoStruct],
    ))
    rslt = self.read_checks(
        'hey',
        collect=query_pb.Query.CollectChecks(result_data=True),
        types=[demoStruct],
    )[0]
    self.assertEqual(rslt.results[0].data[0].type_url,
                     turboci.type_url_for(demoStruct))

    self.assertTrue(rslt.results[0].HasField('created_at'))
    created_ts = rslt.results[0].created_at
    self.assertFalse(rslt.results[0].HasField('finalized_at'))

    self.write_nodes(turboci.check(
        'hey',
        finalize_results=True,
    ))
    rslt = self.read_checks('hey')[0]
    self.assertTrue(rslt.results[0].HasField('finalized_at'))
    finalized_ts = rslt.results[0].finalized_at

    self.assertGreater((finalized_ts.ts.seconds, finalized_ts.ts.nanos),
                        (created_ts.ts.seconds, created_ts.ts.nanos))

  def test_query_filter_kind(self) -> None:
    self.write_nodes(
        turboci.check('a', kind='CHECK_KIND_ANALYSIS'),
        turboci.check('b', kind='CHECK_KIND_SOURCE'),
        turboci.check('c', kind='CHECK_KIND_BUILD'),
        turboci.check('cc', kind='CHECK_KIND_BUILD'),
    )

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.SelectChecks.Predicate(kind='CHECK_KIND_ANALYSIS'),
            query_pb.Query.SelectChecks.Predicate(
                kind=check_kind_pb.CheckKind.CHECK_KIND_BUILD),
        )).workplans[0]
    self.assertEqual(len(ret.checks), 3)
    self.assertEqual(self.check_ids(ret.checks), {':Ca', ':Cc', ':Ccc'})

  def test_query_filter_option(self) -> None:
    self.write_nodes(
        turboci.check('a', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
        turboci.check('b', kind='CHECK_KIND_ANALYSIS', options=[demoTS]),
        turboci.check('c', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
    )

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.SelectChecks.Predicate(
                with_option_type=turboci.type_set(demoStruct)),)).workplans[0]
    self.assertEqual(len(ret.checks), 2)
    self.assertEqual(self.check_ids(ret.checks), {':Ca', ':Cc'})

  def test_query_filter_all_options(self) -> None:
    self.write_nodes(
        turboci.check('a', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
        turboci.check('b', kind='CHECK_KIND_ANALYSIS', options=[demoTS]),
        turboci.check('c', kind='CHECK_KIND_ANALYSIS', options=[demoStruct]),
    )

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.SelectChecks(),
            query_pb.Query.CollectChecks(options=True),
        ),
        types=('*',)).workplans[0]
    self.assertEqual(len(ret.checks), 3)
    self.assertEqual(self.check_ids(ret.checks), {':Ca', ':Cb', ':Cc'})
    types = set()
    for check in ret.checks:
      types.update(o.type_url for o in check.options)
    self.assertEqual(types, {value.url(demoStruct), value.url(demoTS)})

  def test_query_filter_result(self) -> None:
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
            query_pb.Query.SelectChecks.Predicate(
                with_result_data_type=turboci.type_set(demoStruct)),
        )).workplans[0]

    self.assertEqual(len(ret.checks), 2)
    self.assertEqual(self.check_ids(ret.checks), {':Ca', ':Cc'})

  def test_query_filter_follow_down(self) -> None:
    # make a simple diamond
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_ANALYSIS',
            deps=turboci.dep_group('b', 'c'),
        ), turboci.check(
            'b',
            kind='CHECK_KIND_TEST',
            deps=turboci.dep_group('d'),
        ), turboci.check(
            'c',
            kind='CHECK_KIND_TEST',
            deps=turboci.dep_group('d'),
        ), turboci.check(
            'd',
            kind='CHECK_KIND_BUILD',
            deps=turboci.dep_group('s'),
        ),
        turboci.check(
            's',
            kind='CHECK_KIND_SOURCE',
            state='CHECK_STATE_FINAL',
        ))

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.SelectChecks.Predicate(kind='CHECK_KIND_ANALYSIS'),
            query_pb.Query.ExpandDependencies(),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':Ca', ':Cb', ':Cc'})

  def test_query_filter_follow_up(self) -> None:
    # make a simple diamond
    self.write_nodes(
        turboci.check(
            'a',
            kind='CHECK_KIND_ANALYSIS',
            deps=turboci.dep_group('b', 'c'),
        ), turboci.check(
            'b',
            kind='CHECK_KIND_TEST',
            deps=turboci.dep_group('d'),
        ), turboci.check(
            'c',
            kind='CHECK_KIND_TEST',
            deps=turboci.dep_group('d'),
        ), turboci.check(
            'd',
            kind='CHECK_KIND_BUILD',
            deps=turboci.dep_group('s'),
        ),
        turboci.check(
            's',
            kind='CHECK_KIND_SOURCE',
            state='CHECK_STATE_FINAL',
        ))

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.SelectChecks.Predicate(
                kind=check_kind_pb.CheckKind.CHECK_KIND_SOURCE),
            query_pb.Query.ExpandDependents(),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':Cs', ':Cd'})

  def test_dependencies_edges(self) -> None:
    self.write_nodes(
        turboci.check('A', kind='CHECK_KIND_BUILD', state='CHECK_STATE_FINAL'),
        turboci.check(
            'B',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'C',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'D',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('B', 'C')),
    )

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.ExpandDependencies(),
            node_set=turboci.collect_check_ids('D'),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':CD', ':CB', ':CC'})

  def test_dependencies_satisfied(self) -> None:
    self.write_nodes(
        turboci.check('A', kind='CHECK_KIND_BUILD', state='CHECK_STATE_FINAL'),
        turboci.check(
            'B',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'C',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'D',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('B', 'C')),
    )

    # d has no satisfied dependencies
    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.ExpandDependencies(
                mode='QUERY_EXPAND_DEPS_MODE_SATISFIED'),
            node_set=turboci.collect_check_ids('D'),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':CD'})

    # Once B and C are final, D should be unblocked
    self.write_nodes(
        turboci.check('B', state='CHECK_STATE_FINAL'),
        turboci.check('C', state='CHECK_STATE_FINAL'),
    )

    # deps of d are satisfied now
    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.ExpandDependencies(
                mode='QUERY_EXPAND_DEPS_MODE_SATISFIED'),
            node_set=turboci.collect_check_ids('D'),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':CD', ':CB', ':CC'})
    check = common.get_check_by_full_id(ret, ':CD')
    assert check
    self.assertEqual(check.state, check_state_pb.CheckState.CHECK_STATE_WAITING)

  def test_dependents_edges(self) -> None:
    self.write_nodes(
        turboci.check('A', kind='CHECK_KIND_BUILD'),
        turboci.check(
            'B',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'C',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'D',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('B', 'C')),
    )

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.ExpandDependents(),
            node_set=turboci.collect_check_ids('A'),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':CA', ':CB', ':CC'})

  def test_dependents_satisfied(self) -> None:
    self.write_nodes(
        turboci.check('A', kind='CHECK_KIND_BUILD'),
        turboci.check(
            'B',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'C',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('A')),
        turboci.check(
            'D',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group('B', 'C')),
    )

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.ExpandDependents(
                mode='QUERY_EXPAND_DEPS_MODE_SATISFIED'),
            node_set=turboci.collect_check_ids('A'),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':CA'})

    self.write_nodes(turboci.check('A', state='CHECK_STATE_FINAL'))

    ret = self.query_nodes(
        turboci.make_query(
            query_pb.Query.ExpandDependents(
                mode='QUERY_EXPAND_DEPS_MODE_SATISFIED'),
            node_set=turboci.collect_check_ids('A'),
        )).workplans[0]
    self.assertEqual(self.check_ids(ret.checks), {':CA', ':CB', ':CC'})

  def test_ab_bc_resolution(self) -> None:
    self.write_nodes(
        turboci.check(
            'p',
            kind='CHECK_KIND_BUILD',
            state='CHECK_STATE_PLANNED',
            deps=turboci.dep_group(
                turboci.dep_group('a', 'b'),
                turboci.dep_group('b', 'c'),
                turboci.dep_group('c', 'd'),
                threshold=1,
            )),
        turboci.check('a', kind='CHECK_KIND_BUILD'),
        turboci.check('b', kind='CHECK_KIND_BUILD'),
        turboci.check('c', kind='CHECK_KIND_BUILD'),
        turboci.check('d', kind='CHECK_KIND_BUILD'),
    )

    p = self.read_checks('p')[0]
    self.assertFalse(p.dependencies.HasField('resolution'))

    # satisfy p->a and p->c
    self.write_nodes(
        turboci.check('a', state='CHECK_STATE_FINAL'),
        turboci.check('c', state='CHECK_STATE_FINAL'),
    )

    # still no resolution yet
    p = self.read_checks('p')[0]
    self.assertFalse(p.dependencies.HasField('resolution'))

    # satisfy p->d
    self.write_nodes(turboci.check('d', state='CHECK_STATE_FINAL'),)

    # resolved
    p = self.read_checks('p')[0]
    self.assertTrue(p.dependencies.HasField('resolution'))
    # and satisfied has the minimal set of just ['c', 'd']
    self.assertEqual(p.dependencies.resolution, edge_pb.RESOLUTION_SATISFIED)

  def test_check_versioning_invariant(self) -> None:
    # 1. Create Check with Option
    self.write_nodes(
        turboci.check(
            'check',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))

    check = self.read_checks(
        'check',
        collect=query_pb.Query.CollectChecks(options=True),
        types=[demoStruct])[0]
    check_v1 = check.version

    # 2. Modify Option
    self.write_nodes(turboci.check(
        'check',
        options=[demoStruct2],
    ))

    check = self.read_checks(
        'check',
        collect=query_pb.Query.CollectChecks(options=True),
        types=[demoStruct])[0]
    check_v2 = check.version

    # Check version SHOULD change
    self.assertGreater((check_v2.ts.seconds, check_v2.ts.nanos),
                       (check_v1.ts.seconds, check_v1.ts.nanos))

    # 3. Add Result (Check version should change because we added a result)
    self.write_nodes(
        turboci.check(
            'check',
            state='CHECK_STATE_WAITING',
            results=[demoStruct],
        ))

    check = self.read_checks(
        'check',
        collect=query_pb.Query.CollectChecks(result_data=True),
        types=[demoStruct])[0]
    check_v3 = check.version

    self.assertGreater((check_v3.ts.seconds, check_v3.ts.nanos),
                       (check_v2.ts.seconds, check_v2.ts.nanos))

    # 4. Modify Result
    self.write_nodes(turboci.check(
        'check',
        results=[demoStruct2],
    ))

    check = self.read_checks(
        'check',
        collect=query_pb.Query.CollectChecks(result_data=True),
        types=[demoStruct])[0]
    check_v4 = check.version

    # Check version SHOULD change
    self.assertGreater((check_v4.ts.seconds, check_v4.ts.nanos),
                       (check_v3.ts.seconds, check_v3.ts.nanos))

  def test_check_option_versioning(self) -> None:
    # 1. Create Check with an initial Option
    self.write_nodes(
        turboci.check(
            'versioned_check',
            kind='CHECK_KIND_BUILD',
            options=[demoStruct],
        ))

    # Read back the initial state
    check = self.read_checks(
        'versioned_check',
        collect=query_pb.Query.CollectChecks(options=True),
        types=[demoStruct])[0]
    check_v1 = check.version

    # 2. Modify the existing Option
    self.write_nodes(turboci.check(
        'versioned_check',
        options=[demoStruct2],
    ))

    # Read back the updated state
    check = self.read_checks(
        'versioned_check',
        collect=query_pb.Query.CollectChecks(options=True),
        types=[demoStruct2])[0]
    check_v2 = check.version

    # Check version MUST change
    self.assertGreater((check_v2.ts.seconds, check_v2.ts.nanos),
                       (check_v1.ts.seconds, check_v1.ts.nanos))

    # 3. Adding a NEW option SHOULD change the check version
    self.write_nodes(turboci.check(
        'versioned_check',
        options=[demoStruct2, demoTS],
    ))

    check = self.read_checks(
        'versioned_check',
        collect=query_pb.Query.CollectChecks(options=True),
        types=[demoStruct2, demoTS])[0]
    check_v3 = check.version
    self.assertGreater((check_v3.ts.seconds, check_v3.ts.nanos),
                       (check_v2.ts.seconds, check_v2.ts.nanos))

  def test_query_check_no_options(self) -> None:
    self.write_nodes(
        turboci.check('A', kind='CHECK_KIND_BUILD', options=[demoStruct]))
    # Query check 'A' without requesting options data
    ret = self.read_checks('A')
    check = ret[0]
    self.assertEqual(len(check.options), 1)
    # Check that value is stripped but type_url is present
    self.assertEqual(check.options[0].type_url,
                     turboci.type_url_for(demoStruct))
    self.assertFalse(check.options[0].inline.value)

  def test_check_state_history(self) -> None:
    # 1. Create in PLANNING
    self.write_nodes(
        turboci.check(
            'check',
            kind='CHECK_KIND_BUILD',
            deps=turboci.dep_group('dep'),
        ),
        turboci.check(
            'dep',
            kind='CHECK_KIND_BUILD',
        )
    )

    check = self.read_checks('check')[0]
    self.assertEqual(check.state,
                     check_state_pb.CheckState.CHECK_STATE_PLANNING)
    self.assertEqual(len(check.state_history), 1)
    self.assertEqual(check.state_history[0].state,
                     check_state_pb.CheckState.CHECK_STATE_PLANNING)
    v1 = check.state_history[0].version

    # 2. Move to PLANNED
    self.write_nodes(turboci.check(
        'check',
        state='CHECK_STATE_PLANNED',
    ))

    check = self.read_checks('check')[0]
    self.assertEqual(check.state, check_state_pb.CheckState.CHECK_STATE_PLANNED)
    self.assertEqual(len(check.state_history), 2)
    self.assertEqual(check.state_history[0].state,
                     check_state_pb.CheckState.CHECK_STATE_PLANNING)
    self.assertEqual(check.state_history[1].state,
                     check_state_pb.CheckState.CHECK_STATE_PLANNED)
    v2 = check.state_history[1].version
    self.assertGreater((v2.ts.seconds, v2.ts.nanos),
                       (v1.ts.seconds, v1.ts.nanos))

    # 3. Move 'dep' to FINAL -> 'check' becomes WAITING
    self.write_nodes(turboci.check(
        'dep',
        state='CHECK_STATE_FINAL',
    ))

    check = self.read_checks('check')[0]
    self.assertEqual(check.state, check_state_pb.CheckState.CHECK_STATE_WAITING)
    self.assertEqual(len(check.state_history), 3)
    self.assertEqual(check.state_history[2].state,
                     check_state_pb.CheckState.CHECK_STATE_WAITING)
    v3 = check.state_history[2].version
    self.assertGreater((v3.ts.seconds, v3.ts.nanos),
                       (v2.ts.seconds, v2.ts.nanos))

    # 4. Move to FINAL
    self.write_nodes(turboci.check(
        'check',
        state='CHECK_STATE_FINAL',
    ))

    check = self.read_checks('check')[0]
    self.assertEqual(check.state, check_state_pb.CheckState.CHECK_STATE_FINAL)
    self.assertEqual(len(check.state_history), 4)
    self.assertEqual(
        check.state_history[3].state,
        check_state_pb.CheckState.CHECK_STATE_FINAL)
    v4 = check.state_history[3].version
    self.assertGreater((v4.ts.seconds, v4.ts.nanos),
                       (v3.ts.seconds, v3.ts.nanos))


if __name__ == '__main__':
  test_env.main()
