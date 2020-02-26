#!/usr/bin/env vpython
# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import test_env

from recipe_engine.internal.warn.definition import (
  _populate_monorail_bug_default_fields,
  _validate,
)

import PB.recipe_engine.warning as warning_pb

def create_definition(
  name, description=None, deadline=None, monorail_bug=None):
  """Shorthand to create a warning definition proto message based on the
  given input"""
  return warning_pb.Definition(
    name = name,
    description = description,
    deadline = deadline,
    monorail_bug = [monorail_bug] if monorail_bug else None,
  )

class TestWarningDefinition(test_env.RecipeEngineUnitTest):
  def test_populate_monorail_bug_default_fields(self):
    # No Default fields specified
    definition = create_definition(
      'WARNING_NAME', monorail_bug=warning_pb.MonorailBug(id=123))
    expected_definition = warning_pb.Definition()
    expected_definition.CopyFrom(definition)
    _populate_monorail_bug_default_fields(
      [definition], warning_pb.MonorailBugDefault())
    self.assertEqual(expected_definition, definition)

    # All Default fields specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug=warning_pb.MonorailBug(project= 'two', id=123))
    _populate_monorail_bug_default_fields(
      [definition], warning_pb.MonorailBugDefault(host='a.com', project='one'))
    expected_definition = create_definition(
      'WARNING_NAME',
      # default project should not override the existing one
      monorail_bug=warning_pb.MonorailBug(host='a.com', project='two', id=123))
    self.assertEqual(expected_definition, definition)

    # Partial fields specified
    definition = create_definition(
      'WARNING_NAME', monorail_bug=warning_pb.MonorailBug(id=123))
    _populate_monorail_bug_default_fields(
      [definition], warning_pb.MonorailBugDefault(host='a.com'))
    expected_definition = create_definition(
      'WARNING_NAME',
      monorail_bug=warning_pb.MonorailBug(host='a.com', id=123))
    self.assertEqual(expected_definition, definition)

  def test_valid_definitions(self):
    simple_definition = create_definition('SIMPLE_WARNING_NAME')
    _validate(simple_definition)
    full_definition = create_definition(
      'FULL_WARNING_NAME',
      description = 'this is a description',
      deadline = '2020-12-31',
      monorail_bug = warning_pb.MonorailBug(
        host='bugs.chromium.org', project= 'chromium', id=123456),
    )
    _validate(full_definition)

  def test_invalid_warning_name(self):
    with self.assertRaises(ValueError):
      _validate(create_definition('ThisIsCamalCase'))

  def test_invalid_monorail_bug(self):
    # No host specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug = warning_pb.MonorailBug(project='chromium', id=123456),
      )
    with self.assertRaises(ValueError):
      _validate(definition)
    # No project specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug = warning_pb.MonorailBug(
        host='bugs.chromium.org', id=123456),
      )
    with self.assertRaises(ValueError):
      _validate(definition)
    # No id specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug = warning_pb.MonorailBug(
        host='bugs.chromium.org', project='chromium'),
      )
    with self.assertRaises(ValueError):
      _validate(definition)

  def test_invalid_deadline(self):
    with self.assertRaises(ValueError):
      _validate(create_definition(
        'WARNING_NAME', deadline='12-31-2020'))

    with self.assertRaises(ValueError):
      _validate(create_definition(
        'WARNING_NAME', deadline='2020-12-31T23:59:59'))

if __name__ == '__main__':
  test_env.main()
