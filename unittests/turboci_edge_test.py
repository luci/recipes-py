#!/usr/bin/env vpython3
# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from copy import deepcopy

import test_env

from PB.turboci.graph.orchestrator.v1.check import Check
from PB.turboci.graph.orchestrator.v1.check_state import CHECK_STATE_FINAL
from PB.turboci.graph.orchestrator.v1.edge import Edge
from PB.turboci.graph.orchestrator.v1.edge_group import EdgeGroup
from PB.turboci.graph.orchestrator.v1.revision import Revision
from PB.turboci.graph.orchestrator.v1.stage import Stage
from PB.turboci.graph.orchestrator.v1.stage_state import StageState

from recipe_engine.internal.turboci import common
from recipe_engine.internal.turboci import edge
from recipe_engine.internal.turboci.common import check_id, edge_group, stage_id
from recipe_engine.internal.turboci.ids import from_id, wrap_id

_EG_TREE = [
    edge_group(
        "something",
        "else",
        edge_group("alternately", "both"),
        threshold=1,
    ),
    edge_group("all", "these", stages=["cool"]),
]


class TestEdgeGroupVisitor(test_env.RecipeEngineUnitTest):

  def test_ok(self):
    acc = []

    class _visitor(edge.GroupVisitor):

      def visit_group(self, group: EdgeGroup) -> bool:
        acc.append('visit_group')
        return True

      def leave_group(self, group: EdgeGroup):
        acc.append('leave_group')

      def visit_edge(self, edge: Edge):
        acc.append(f'visit_edge[{from_id(edge.target)!r}]')

    _visitor().visit(*_EG_TREE)
    self.assertEqual(acc, [
        'visit_group', 'visit_group', "visit_edge['L:Calternately']",
        "visit_edge['L:Cboth']", 'leave_group', "visit_edge['L:Csomething']",
        "visit_edge['L:Celse']", 'leave_group', 'visit_group',
        "visit_edge['L:Call']", "visit_edge['L:Cthese']",
        "visit_edge['L:Scool']", 'leave_group'
    ])

  def test_filter_check(self):
    acc = []

    class _visitor(edge.GroupVisitor):
      edge_filter = 'check'

      def visit_group(self, group: EdgeGroup) -> bool:
        acc.append('visit_group')
        return True

      def leave_group(self, group: EdgeGroup):
        acc.append('leave_group')

      def visit_edge(self, edge: Edge):
        acc.append(f'visit_edge[{from_id(edge.target)!r}]')

    _visitor().visit(*_EG_TREE)
    self.assertEqual(acc, [
        'visit_group', 'visit_group', "visit_edge['L:Calternately']",
        "visit_edge['L:Cboth']", 'leave_group', "visit_edge['L:Csomething']",
        "visit_edge['L:Celse']", 'leave_group', 'visit_group',
        "visit_edge['L:Call']", "visit_edge['L:Cthese']", 'leave_group'
    ])

  def test_filter_stage(self):
    acc = []

    class _visitor(edge.GroupVisitor):
      edge_filter = 'stage'

      def visit_group(self, group: EdgeGroup) -> bool:
        acc.append('visit_group')
        return True

      def leave_group(self, group: EdgeGroup):
        acc.append('leave_group')

      def visit_edge(self, edge: Edge):
        acc.append(f'visit_edge[{from_id(edge.target)!r}]')

    _visitor().visit(*_EG_TREE)
    self.assertEqual(acc, [
        'visit_group', 'visit_group', 'leave_group', 'leave_group',
        'visit_group', "visit_edge['L:Scool']", 'leave_group'
    ])


class TestExtractTargetIDs(test_env.RecipeEngineUnitTest):

  def test_checks_ok(self):
    ids = edge.extract_target_ids(*_EG_TREE, want='check')
    self.assertEqual(
        ids, {
            "L:Csomething": wrap_id(check_id("something")),
            "L:Cthese": wrap_id(check_id("these")),
            "L:Call": wrap_id(check_id("all")),
            "L:Cboth": wrap_id(check_id("both")),
            "L:Calternately": wrap_id(check_id("alternately")),
            "L:Celse": wrap_id(check_id("else")),
        })

  def test_stages_ok(self):
    ids = edge.extract_target_ids(*_EG_TREE, want='stage')
    self.assertEqual(ids, {
        "L:Scool": wrap_id(stage_id("cool")),
    })

  def test_all_ok(self):
    ids = edge.extract_target_ids(*_EG_TREE, want='*')
    self.assertEqual(
        ids, {
            "L:Csomething": wrap_id(check_id("something")),
            "L:Cthese": wrap_id(check_id("these")),
            "L:Call": wrap_id(check_id("all")),
            "L:Cboth": wrap_id(check_id("both")),
            "L:Calternately": wrap_id(check_id("alternately")),
            "L:Celse": wrap_id(check_id("else")),
            "L:Scool": wrap_id(stage_id("cool")),
        })

  def test_only_resolved(self):
    egTree = deepcopy(_EG_TREE)
    egTree[0].groups[0].edges[1].resolution.satisfied = True
    egTree[0].edges[1].resolution.satisfied = False

    ids = edge.extract_target_ids(*egTree, want='check', satisfied=True)
    self.assertEqual(ids, {
        "L:Cboth": wrap_id(check_id("both")),
    })

    ids = edge.extract_target_ids(*egTree, want='check', satisfied=False)
    self.assertEqual(ids, {
        "L:Celse": wrap_id(check_id("else")),
    })


class TestResolveEdges(test_env.RecipeEngineUnitTest):

  def setUp(self):
    self.now = Revision()
    self.now.ts.seconds = 1234
    self.now.ts.nanos = 5678

    self.egTree = deepcopy(_EG_TREE)

    self.targ = Check(state=CHECK_STATE_FINAL)

    return super().setUp()

  def test_nop(self):
    self.targ.identifier.id = "cool"
    self.assertFalse(
        edge.resolve_edges(*self.egTree, at=self.now, targets=[self.targ]))
    self.assertEqual(self.egTree, _EG_TREE)  # no changes

  def test_one(self):
    self.targ.identifier.id = "something"  # enough to unblock first group
    self.assertFalse(
        edge.resolve_edges(*self.egTree, at=self.now, targets=[self.targ]))
    self.assertTrue(self.egTree[0].resolution.satisfied)
    self.assertFalse(self.egTree[1].HasField('resolution'))

  def test_two(self):
    self.targ.identifier.id = "something"  # enough to unblock first group
    self.assertFalse(
        edge.resolve_edges(*self.egTree, at=self.now, targets=[self.targ]))

    self.targ.identifier.id = "all"  # enough to unblock first group
    self.assertFalse(
        edge.resolve_edges(*self.egTree, at=self.now, targets=[self.targ]))

    self.targ.identifier.id = "these"  # enough to unblock first group
    self.assertFalse(
        edge.resolve_edges(*self.egTree, at=self.now, targets=[self.targ]))

    stageTarg = Stage(
        identifier=stage_id("cool"),
        state=StageState.STAGE_STATE_FINAL,
    )
    self.assertTrue(
        edge.resolve_edges(*self.egTree, at=self.now, targets=[stageTarg]))

    self.assertTrue(self.egTree[0].resolution.satisfied)
    self.assertTrue(self.egTree[1].resolution.satisfied)


class TestPruneEmptyGroups(test_env.RecipeEngineUnitTest):

  def test_ok(self):
    group = [common.edge_group(common.edge_group())]
    edge.prune_empty_groups(group)
    self.assertEqual(group, [])

  def test_absorb(self):
    group = [
        common.edge_group(
            common.edge_group(),
            common.edge_group('hey'),
        ),
        common.edge_group('not empty')
    ]
    edge.prune_empty_groups(group)
    self.assertEqual(group, [
        common.edge_group('hey'),
        common.edge_group('not empty'),
    ])


if __name__ == '__main__':
  test_env.main()
