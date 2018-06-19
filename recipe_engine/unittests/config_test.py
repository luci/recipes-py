#!/usr/bin/env vpython
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import unittest

import test_env

from recipe_engine import config
from recipe_engine import doc_pb2 as doc


d = doc.Doc


class TestConfigGroupSchema(unittest.TestCase):
  def testNewReturnsConfigGroup(self):
    schema = config.ConfigGroupSchema(test=config.Single(int))

    self.assertIsInstance(schema.new(test=3), config.ConfigGroup)

  def testCallCallsNew(self):
    schema = config.ConfigGroupSchema(test=config.Single(int))
    sentinel = object()
    schema.new = lambda *args, **kwargs: sentinel

    self.assertEqual(schema(test=3), sentinel)

  def testMustHaveTypeMap(self):
    with self.assertRaises(ValueError):
      config.ConfigGroupSchema()

class TestProperties(unittest.TestCase):
  def testSimpleReturn(self):
    pass

class TestEnum(unittest.TestCase):
  def testEnum(self):
    schema = config.ConfigGroupSchema(test=config.Enum('foo', 'bar'))
    self.assertIsInstance(schema.new(test='foo'), config.ConfigGroup)

  def testMustBeOneOf(self):
    schema = config.ConfigGroupSchema(test=config.Enum('foo', 'bar'))
    with self.assertRaises(ValueError):
      schema.new(test='baz')


class TestSchemaProto(unittest.TestCase):
  def test_config_group(self):
    cg = config.ConfigGroup(
      combo=config.Single((int, float), empty_val=20),
      other=config.List(str),
      field=config.Single((str, type(None))),
    )

    self.assertEqual(
      cg.schema_proto(),
      d.Schema(struct=d.Schema.Struct(type_map={
        'combo': d.Schema(single=d.Schema.Single(
          inner_type=[d.Schema.NUMBER],
          required=True,
          default_json='20',
        )),
        'other': d.Schema(list=d.Schema.List(
          inner_type=[d.Schema.STRING],
        )),
        'field': d.Schema(single=d.Schema.Single(
          inner_type=[d.Schema.STRING, d.Schema.NULL],
          required=True,
          default_json='null',
        )),
      })))

  def test_config_group_schema(self):
    cg = config.ConfigGroupSchema(
      combo=config.Single((int, float), empty_val=20),
      other=config.List(str),
      field=config.Single((str, type(None))),
    )

    self.assertEqual(
      cg.schema_proto(),
      d.Schema(struct=d.Schema.Struct(type_map={
        'combo': d.Schema(single=d.Schema.Single(
          inner_type=[d.Schema.NUMBER],
          required=True,
          default_json='20',
        )),
        'other': d.Schema(list=d.Schema.List(
          inner_type=[d.Schema.STRING],
        )),
        'field': d.Schema(single=d.Schema.Single(
          inner_type=[d.Schema.STRING, d.Schema.NULL],
          required=True,
          default_json='null',
        )),
      })))

  def test_config_list(self):
    cl = config.ConfigList(lambda: config.ConfigGroup(
      a = config.Single(bool),
      b = config.Single(dict),
    ))

    self.assertEqual(
      cl.schema_proto(),
      d.Schema(sequence=d.Schema.Sequence(
        inner_type=d.Schema(struct=d.Schema.Struct(type_map={
          'a': d.Schema(single=d.Schema.Single(
            inner_type=[d.Schema.BOOLEAN],
            required=True,
            default_json='null',
          )),
          'b': d.Schema(single=d.Schema.Single(
            inner_type=[d.Schema.OBJECT],
            required=True,
            default_json='null',
          ))
        }))
      ))
    )

  def test_dict(self):
    cd = config.Dict(value_type=list)
    self.assertEqual(
      cd.schema_proto(),
      d.Schema(dict=d.Schema.Dict(
        value_type=[d.Schema.ARRAY],
      ))
    )

  def test_set(self):
    cd = config.Set(str)
    self.assertEqual(
      cd.schema_proto(),
      d.Schema(set=d.Schema.Set(
        inner_type=[d.Schema.STRING],
      ))
    )

  def test_list(self):
    cd = config.List((int, type(None)))
    self.assertEqual(
      cd.schema_proto(),
      d.Schema(list=d.Schema.List(
        inner_type=[d.Schema.NUMBER, d.Schema.NULL],
      ))
    )

  def test_static(self):
    cd = config.Static("hello")
    self.assertEqual(
      cd.schema_proto(),
      d.Schema(static=d.Schema.Static(
        default_json='"hello"',
      ))
    )

  def test_enum(self):
    cd = config.Enum("hello", "world")
    self.assertEqual(
      cd.schema_proto(),
      d.Schema(enum=d.Schema.Enum(
        values_json=[
          '"hello"',
          '"world"',
        ],
        required=True,
      ))
    )


if __name__ == '__main__':
  unittest.main()
