#!/usr/bin/env vpython3
# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import test_env

from PB.turboci.graph.orchestrator.v1 import check as check_pb
from PB.turboci.graph.orchestrator.v1 import check_state as check_state_pb
from PB.turboci.graph.orchestrator.v1 import dependencies as dependencies_pb
from PB.turboci.graph.orchestrator.v1 import edge as edge_pb
from PB.turboci.graph.orchestrator.v1 import revision as revision_pb
from PB.turboci.graph.orchestrator.v1 import stage as stage_pb
from PB.turboci.graph.orchestrator.v1 import (
    write_nodes_request as write_nodes_request_pb,
)

from recipe_engine import turboci
from recipe_engine.internal.turboci import edge


class TestExtractDependencies(test_env.RecipeEngineUnitTest):
  def test_ok(self) -> None:
    deps = edge.extract_dependencies(
        turboci.dep_group(
            turboci.dep_group('a', 'b'),
            turboci.dep_group('b', 'c'),
            threshold=1,
        ))
    self.assertEqual(
        deps,
        dependencies_pb.Dependencies(
            edges=[
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('a'))),
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('b'))),
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('c'))),
            ],
            predicate=dependencies_pb.Dependencies.Group(
                groups=[
                    dependencies_pb.Dependencies.Group(edges=[0, 1]),
                    dependencies_pb.Dependencies.Group(edges=[1, 2]),
                ],
                threshold=1,
            ),
        ))

  def test_check_cannot_depend_on_stage(self) -> None:
    with self.assertRaises(turboci.InvalidArgumentException):
      edge.extract_dependencies(turboci.dep_group(stages=['foo']))

  def test_bad_thresholds(self) -> None:
    with self.assertRaises(turboci.InvalidArgumentException):
      dg = turboci.dep_group('foo')
      dg.threshold = 2  # dep_group has its own check
      edge.extract_dependencies(dg)

    with self.assertRaises(turboci.InvalidArgumentException):
      dg = turboci.dep_group('foo')
      dg.threshold = -1  # dep_group has its own check
      edge.extract_dependencies(dg)

  def test_normalizes_threshold(self) -> None:
    dg = (turboci.dep_group('foo'))
    dg.threshold = 1
    deps = edge.extract_dependencies(dg)
    self.assertEqual(deps.predicate.threshold, 0)

  def test_absorb(self) -> None:
    deps = edge.extract_dependencies(
        turboci.dep_group(
            turboci.dep_group(turboci.dep_group(
                'a',
                'b',
            ),),
            threshold=1,
        ))
    self.assertEqual(
        deps,
        dependencies_pb.Dependencies(
            edges=[
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('a'))),
                edge_pb.Edge(
                    check=edge_pb.Edge.Check(
                        identifier=turboci.check_id('b'))),
            ],
            predicate=dependencies_pb.Dependencies.Group(edges=[0, 1],)))

  def test_empty(self) -> None:
    deps = edge.extract_dependencies(turboci.dep_group())
    self.assertEqual(
        deps,
        dependencies_pb.Dependencies(
            predicate=dependencies_pb.Dependencies.Group(),))

  def test_empty_subgroup(self) -> None:
    with self.assertRaises(turboci.InvalidArgumentException):
      edge.extract_dependencies(
          turboci.dep_group(turboci.dep_group(turboci.dep_group(),),))


class TestDependencyIndex(test_env.RecipeEngineUnitTest):

  def setUp(self) -> None:
    self.di = edge.DependencyIndex()
    self.ccri = edge.CheckCondition(
        check_state_pb.CheckState.CHECK_STATE_FINAL, "true")
    self.nodes: dict[str, check_pb.Check | stage_pb.Stage] = {}
    self.now = revision_pb.Revision()
    self.now.ts.seconds = 12345

    return super().setUp()

  def get_check(self, name: str) -> check_pb.Check:
    ident = turboci.check_id(name)
    ident_str = turboci.from_id(ident)

    cur = self.nodes.get(ident_str)
    if cur:
      assert isinstance(cur, check_pb.Check)
      return cur

    cur = check_pb.Check(identifier=ident, state='CHECK_STATE_PLANNING')
    self.nodes[ident_str] = cur
    return cur

  def must_get_existing_check(self, ident_str: str) -> check_pb.Check:
    ret = self.nodes[ident_str]
    if isinstance(ret, check_pb.Check):
      return ret
    raise AssertionError(f'{ident_str!r} is not a Check: {type(ret).__name__}')

  def set_dependencies(
      self,
      name: str,
      deps: write_nodes_request_pb.WriteNodesRequest.DependencyGroup,
      *,
      do_index: bool = True,
  ) -> None:
    """Writes dependencies for check `name`.

    If `do_index` is True, calls ensure_conditions and index_predicate for the
    check `name`. Uses node.state != PLANNING for mark_immutable. Then calls
    index_node_write(node)."""
    node = self.get_check(name)
    node.dependencies.CopyFrom(edge.extract_dependencies(deps))
    if do_index:
      self.di.ensure_conditions(node.dependencies.edges, self.nodes.get)
      self.di.index_predicate(
          turboci.from_id(node.identifier),
          node.dependencies,
          self.now,
          mark_immutable=(
              node.state != check_state_pb.CheckState.CHECK_STATE_PLANNING
          ))
      self.di.index_node_write(node)

  def test_add_remove(self) -> None:
    a = self.get_check('A')
    a_id = turboci.from_id(a.identifier)
    b = self.get_check('B')
    b_id = turboci.from_id(b.identifier)
    c = self.get_check('C')
    c_id = turboci.from_id(c.identifier)

    self.set_dependencies('A', turboci.dep_group('B', 'C'))

    self.assertEqual(
        self.di._data, {
            a_id:
                edge.DependencyIndex._Entry(edges_flat={b_id, c_id},),
            b_id:
                edge.DependencyIndex._Entry(
                    conditions={self.ccri: edge_pb.RESOLUTION_UNKNOWN},
                    dependents={a_id},
                ),
            c_id:
                edge.DependencyIndex._Entry(
                    conditions={self.ccri: edge_pb.RESOLUTION_UNKNOWN},
                    dependents={a_id},
                ),
        })

    self.set_dependencies('A', turboci.dep_group('B'))

    self.assertEqual(
        self.di._data, {
            a_id:
                edge.DependencyIndex._Entry(edges_flat={b_id},),
            b_id:
                edge.DependencyIndex._Entry(
                    conditions={self.ccri: edge_pb.RESOLUTION_UNKNOWN},
                    dependents={a_id},
                ),
            c_id:
                edge.DependencyIndex._Entry(
                    conditions={self.ccri: edge_pb.RESOLUTION_UNKNOWN},),
        })

  def test_evaluate_conditions(self) -> None:
    b = self.get_check('B')
    b_id = turboci.from_id(b.identifier)

    self.set_dependencies('A', turboci.dep_group('B'))

    self.assertEqual(self.di._data[b_id].conditions, {
        self.ccri: edge_pb.RESOLUTION_UNKNOWN,
    })

    self.di.index_node_write(b)

    self.assertEqual(
        self.di._data[b_id].conditions,
        {self.ccri: edge_pb.RESOLUTION_UNKNOWN})
    self.assertFalse(self.di.has_events())

    b.state = check_state_pb.CheckState.CHECK_STATE_FINAL

    self.di.index_node_write(b)  # resolves default conditions

    self.assertEqual(
        self.di._data[b_id].conditions,
        {self.ccri: edge_pb.RESOLUTION_SATISFIED})
    self.assertEqual(self.di._resolution_events, {
        edge.DependencyIndex._ResolutionEvent(
            b_id, self.ccri, edge_pb.RESOLUTION_SATISFIED),
    })
    self.assertTrue(self.di.has_events())

    self.di.index_node_write(b)  # no-op

    self.assertEqual(
        self.di._data[b_id].conditions,
        {self.ccri: edge_pb.RESOLUTION_SATISFIED})
    self.assertEqual(self.di._resolution_events, {
        edge.DependencyIndex._ResolutionEvent(
            b_id, self.ccri, edge_pb.RESOLUTION_SATISFIED),
    })

  def test_process_queue(self) -> None:
    a = self.get_check('A')
    a_id = turboci.from_id(a.identifier)
    b = self.get_check('B')

    a.state = check_state_pb.CheckState.CHECK_STATE_PLANNED
    self.set_dependencies('A', turboci.dep_group('B'))

    b.state = check_state_pb.CheckState.CHECK_STATE_FINAL
    self.di.index_node_write(b)

    write = self.di.process_queue(self.must_get_existing_check, self.now)

    self.assertEqual(
        write, {
            a_id:
                dependencies_pb.Dependencies(
                    edges=a.dependencies.edges,
                    predicate=a.dependencies.predicate,
                    resolution_events={
                        0:
                            dependencies_pb.Dependencies.ResolutionEvent(
                                version=self.now,
                                resolution=edge_pb.RESOLUTION_SATISFIED),
                    },
                    resolution=edge_pb.RESOLUTION_SATISFIED,
                )
        })

    self.assertFalse(self.di.has_events())

    # try adding a new check depending on 'B'

    c = self.get_check('C')
    c.state = check_state_pb.CheckState.CHECK_STATE_PLANNED

    self.set_dependencies('C', turboci.dep_group('B'))

    self.assertEqual(
        c.dependencies,
        dependencies_pb.Dependencies(
            edges=[
                edge_pb.Edge(check=edge_pb.Edge.Check(identifier=b.identifier))
            ],
            predicate=dependencies_pb.Dependencies.Group(edges=[0]),
            resolution_events={
                0:
                    dependencies_pb.Dependencies.ResolutionEvent(
                        version=self.now,
                        resolution=edge_pb.RESOLUTION_SATISFIED),
            },
            resolution=edge_pb.RESOLUTION_SATISFIED,
        ))

  def test_two_nodes(self) -> None:
    a = self.get_check('A')
    a_id = turboci.from_id(a.identifier)
    b = self.get_check('B')
    b_id = turboci.from_id(b.identifier)

    a.state = check_state_pb.CheckState.CHECK_STATE_PLANNED
    self.set_dependencies('A', turboci.dep_group('B'))

    self.assertEqual(
        self.di._data, {
            a_id:
                edge.DependencyIndex._Entry(
                    edges_flat={b_id},
                    state=edge._DepsState.RECEIVING_EVENTS,
                ),
            b_id:
                edge.DependencyIndex._Entry(
                    conditions={self.ccri: edge_pb.RESOLUTION_UNKNOWN},
                    dependents={a_id},
                ),
        })
    # We have new conditions for B, but nothing is resolved yet, so don't need
    # to propagate anything.
    self.assertFalse(self.di.has_events())

    # now resolve b
    b.state = check_state_pb.CheckState.CHECK_STATE_FINAL
    self.set_dependencies('B', turboci.dep_group())

    # we have an event waiting to process
    self.assertEqual(
        self.di._data, {
            a_id:
                edge.DependencyIndex._Entry(
                    edges_flat={b_id},
                    state=edge._DepsState.RECEIVING_EVENTS,
                ),
            b_id:
                edge.DependencyIndex._Entry(
                    conditions={self.ccri: edge_pb.RESOLUTION_SATISFIED},
                    dependents={a_id},
                    state=edge._DepsState.RECEIVING_EVENTS,
                ),
        })

    self.assertEqual(
        self.di._resolution_events, {
            edge.DependencyIndex._ResolutionEvent(
                node_ident_str=b_id,
                condition=self.ccri,
                resolution=edge_pb.RESOLUTION_SATISFIED,
            )
        })

    # When we process the queue, we'll see that `a` needs to be written
    to_write = self.di.process_queue(self.must_get_existing_check, self.now)
    self.assertEqual(
        to_write, {
            a_id:
                dependencies_pb.Dependencies(
                    edges=[
                        edge_pb.Edge(
                            check=edge_pb.Edge.Check(identifier=b.identifier))
                    ],
                    predicate=dependencies_pb.Dependencies.Group(edges=[0]),
                    resolution_events={
                        0:
                            dependencies_pb.Dependencies.ResolutionEvent(
                                version=self.now,
                                resolution=edge_pb.RESOLUTION_SATISFIED),
                    },
                    resolution=edge_pb.RESOLUTION_SATISFIED,
                )
        })

  def test_one_nodes_no_deps(self) -> None:
    a = self.get_check('A')
    a_id = turboci.from_id(a.identifier)

    self.set_dependencies('A', turboci.dep_group())

    self.assertEqual(self.di._data, {
        a_id: edge.DependencyIndex._Entry(),
    })

    # we can process the queue, but this won't do any propagation.
    self.assertEqual(
        self.di.process_queue(self.must_get_existing_check, self.now), {})
    self.assertFalse(self.di.has_events())

    # now resolve a
    a.state = check_state_pb.CheckState.CHECK_STATE_FINAL
    self.set_dependencies('A', turboci.dep_group())

    self.assertEqual(a.dependencies.resolution, edge_pb.RESOLUTION_SATISFIED)


if __name__ == '__main__':
  test_env.main()
