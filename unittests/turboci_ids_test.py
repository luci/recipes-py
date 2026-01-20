#!/usr/bin/env vpython3
# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations
from dataclasses import dataclass

from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp

import test_env

from PB.turboci.graph.ids.v1 import identifier

from recipe_engine.internal.turboci.ids import (
  AnyIdentifier, check_id, collect_check_ids, from_id, stage_id, to_id, type_url_for, type_urls, wrap_id
)


class TypeURLForTest(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    self.assertEqual(
        type_url_for(Struct()),
        "type.googleapis.com/google.protobuf.Struct")
    self.assertEqual(
        type_url_for(Struct),
        "type.googleapis.com/google.protobuf.Struct")

  def test_fail(self):
    with self.assertRaises(Exception):
      type_url_for(None)  # pyright: ignore


_testTS = Timestamp(seconds=12345, nanos=7890)

@dataclass
class _id_test_case:
  kind: str
  ident: AnyIdentifier
  ident_str: str
  note: str = ""

  @property
  def name(self):
    if self.note:
      return f'{self.kind} ({self.note})'
    return self.kind

_test_cases: list[_id_test_case] = [
  _id_test_case(
      "work_plan",
      identifier.WorkPlan(id="1234567"),
      "L1234567"),

  _id_test_case(
      "check",

      identifier.Check(
          work_plan=identifier.WorkPlan(id="1234567"),
          id="cool/beans & stuff",
      ),
      "L1234567:Ccool/beans & stuff"),

  _id_test_case(
      "check_option",
      identifier.CheckOption(
          check=identifier.Check(
              work_plan=identifier.WorkPlan(id="1234567"),
              id="cool/beans & stuff"),
          idx=8,
      ),
      "L1234567:Ccool/beans & stuff:O8"),

  _id_test_case(
      "check_result",
      identifier.CheckResult(
          check=identifier.Check(
              work_plan=identifier.WorkPlan(id="1234567"),
              id="cool/beans & stuff"),
          idx=3,
      ),
      "L1234567:Ccool/beans & stuff:R3"),

  _id_test_case(
      "check_result_datum",
      identifier.CheckResultDatum(
          result=identifier.CheckResult(
              check=identifier.Check(
                work_plan=identifier.WorkPlan(id="1234567"),
                id="cool/beans & stuff"),
              idx=3),
          idx=8,
      ),
      "L1234567:Ccool/beans & stuff:R3:D8"),

  _id_test_case(
      "check_edit",
      identifier.CheckEdit(
          check=identifier.Check(
              work_plan=identifier.WorkPlan(id="1234567"),
              id="cool/beans & stuff"),
          version=_testTS,
      ),
      "L1234567:Ccool/beans & stuff:V12345/7890"),

  _id_test_case(
      "check_edit_reason",
      identifier.CheckEditReason(
          check_edit=identifier.CheckEdit(
              check=identifier.Check(
                  work_plan=identifier.WorkPlan(id="1234567"),
                  id="cool/beans & stuff"),
              version=_testTS,
          ),
          idx=3,
      ),
      "L1234567:Ccool/beans & stuff:V12345/7890:R3"),

  _id_test_case(
      "check_edit_option",
      identifier.CheckEditOption(
          check_edit=identifier.CheckEdit(
              check=identifier.Check(
                  work_plan=identifier.WorkPlan(id="1234567"),
                  id="cool/beans & stuff"),
              version=_testTS),
          idx=2,
      ),
      "L1234567:Ccool/beans & stuff:V12345/7890:O2"),

  _id_test_case(
      "stage",
      identifier.Stage(
          work_plan=identifier.WorkPlan(id="1234567"),
          is_worknode=True,
          id="938215823",
      ),
      "L1234567:N938215823",
      note="worknode",
  ),

  _id_test_case(
      "stage",
      identifier.Stage(
          work_plan=identifier.WorkPlan(id="1234567"),
          is_worknode=False,
          id="some stuff that is awesome",
      ),
      "L1234567:Ssome stuff that is awesome",
  ),

  _id_test_case(
      "stage_attempt",
      identifier.StageAttempt(
          stage=identifier.Stage(
            work_plan=identifier.WorkPlan(id="1234567"),
            is_worknode=True,
            id="938215823"),
          idx=3,
      ),
      "L1234567:N938215823:A3",
      note="worknode",
  ),

  _id_test_case(
      "stage_attempt",
      identifier.StageAttempt(
          stage=identifier.Stage(
            work_plan=identifier.WorkPlan(id="1234567"),
            is_worknode=False,
            id="some stuff that is awesome"),
          idx=3,
      ),
      "L1234567:Ssome stuff that is awesome:A3",
  ),

  _id_test_case(
      "stage_edit",
      identifier.StageEdit(
          stage=identifier.Stage(
            work_plan=identifier.WorkPlan(id="1234567"),
            is_worknode=True,
            id="938215823"),
          version=_testTS,
      ),
      "L1234567:N938215823:V12345/7890",
      note="worknode",
  ),

  _id_test_case(
      "stage_edit",
      identifier.StageEdit(
          stage=identifier.Stage(
            work_plan=identifier.WorkPlan(id="1234567"),
            is_worknode=False,
            id="some stuff that is awesome"),
          version=_testTS,
      ),
      "L1234567:Ssome stuff that is awesome:V12345/7890",
  ),


  _id_test_case(
      "stage_edit_reason",
      identifier.StageEditReason(
          stage_edit=identifier.StageEdit(
              stage=identifier.Stage(
                work_plan=identifier.WorkPlan(id="1234567"),
                is_worknode=False,
                id="some stuff that is awesome"),
              version=_testTS,
          ),
          idx=3,
      ),
      "L1234567:Ssome stuff that is awesome:V12345/7890:R3"),

]


class ToFromIDTest(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    for tc in _test_cases:
      with self.subTest(kind=tc.name):
        self.assertEqual(from_id(tc.ident), tc.ident_str)
        self.assertEqual(from_id(wrap_id(tc.ident)), tc.ident_str)
        self.assertEqual(to_id(tc.ident_str), wrap_id(tc.ident))


class TestWrap(test_env.RecipeEngineUnitTest):
  def test_wrap_id(self):
    for tc in _test_cases:
      with self.subTest(kind=tc.name):
        self.assertIsInstance(wrap_id(tc.ident), identifier.Identifier)
        self.assertEqual(wrap_id(tc.ident).WhichOneof('type'), tc.kind)


class TestCollectCheckIDs(test_env.RecipeEngineUnitTest):
  def test_ok_str(self):
    ids = list(collect_check_ids("hello", "goodbye"))
    self.assertListEqual(ids, [
      wrap_id(identifier.Check(id="hello")),
      wrap_id(identifier.Check(id="goodbye")),
    ])

  def test_ok_ident(self):
    ids = list(collect_check_ids(
        identifier.Check(work_plan=identifier.WorkPlan(id="123"), id="hello"),
        identifier.Check(work_plan=identifier.WorkPlan(id="123"), id="goodbye"),
    ))
    self.assertListEqual(ids, [
      wrap_id(identifier.Check(work_plan=identifier.WorkPlan(id="123"), id="hello")),
      wrap_id(identifier.Check(work_plan=identifier.WorkPlan(id="123"), id="goodbye")),
    ])

  def test_ok_mix(self):
    ids = list(collect_check_ids(
        identifier.Check(work_plan=identifier.WorkPlan(id="123"), id="hello"),
        "goodbye",
        in_workplan="321",
    ))
    self.assertListEqual(ids, [
      wrap_id(identifier.Check(work_plan=identifier.WorkPlan(id="123"), id="hello")),
      wrap_id(identifier.Check(work_plan=identifier.WorkPlan(id="321"), id="goodbye")),
    ])

  def test_bad_id(self):
    with self.assertRaisesRegex(ValueError, 'must not contain ":"'):
      list(collect_check_ids("something:stuff"))


class TestStageID(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    self.assertEqual(stage_id('fleem'), identifier.Stage(id="Sfleem"))
    self.assertEqual(stage_id('fleem', in_workplan='123'),
                     identifier.Stage(
                         work_plan=identifier.WorkPlan(id="123"), id="Sfleem"))
    self.assertEqual(stage_id('fleem', in_workplan='123', is_worknode=True),
                     identifier.Stage(
                         work_plan=identifier.WorkPlan(id="123"), id="Nfleem"))


class TestCheckID(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    self.assertEqual(check_id('fleem'), identifier.Check(id="fleem"))
    self.assertEqual(check_id('fleem', in_workplan='123'),
                     identifier.Check(
                         work_plan=identifier.WorkPlan(id="123"), id="fleem"))


class TestTypeURLs(test_env.RecipeEngineUnitTest):
  def test_ok(self):
    urls = list(type_urls(
        "type.googleapis.com/fictional.package.Message",
        Struct,
    ))
    self.assertEqual(urls, [
        "type.googleapis.com/fictional.package.Message",
        "type.googleapis.com/google.protobuf.Struct",
    ])

  def test_error(self):
    with self.assertRaisesRegex(ValueError, "must start with"):
      list(type_urls("fictional.package.Messsage"))

if __name__ == '__main__':
  test_env.main()
