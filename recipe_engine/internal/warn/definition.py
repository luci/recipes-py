# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import errno
import re

from datetime import datetime
from io import open

from google.protobuf import text_format as textpb

# The relative path to the file where all warnings are defined under recipe
# path (where the "recipes" and/or "recipe_modules" directories sit)
RECIPE_WARNING_DEFINITIONS_REL = 'recipe.warnings'

def parse_warning_definitions(file_path):
  """Parse the warning definition file at the given absolute path. The file
  content is expected to be in text proto format of warning.DefinitionCollection
  proto message. Duplicate warning names will be raised. Each warning definition
  will be validated. The conditions are documented in warning.proto.

  Args:
    * file_path (str) - Absolute path to warning definition file

  Returns a dict of warning name to warning.Definition proto message instance
  """
  raw_text = ''
  try:
    with open(file_path, encoding='utf-8') as f:
      raw_text = f.read()
  except IOError as ex:
    if ex.errno == errno.ENOENT:
      # No warning defined
      return {}
    raise ex

  from PB.recipe_engine.warning import DefinitionCollection
  definition_collection = textpb.Parse(raw_text, DefinitionCollection())
  definitions = list(definition_collection.warning)

  if definition_collection.HasField('monorail_bug_default'):
    _populate_monorail_bug_default_fields(
      definitions, definition_collection.monorail_bug_default)

  ret = {}
  for definition in definitions:
    if definition.name in ret:
      raise ValueError(
        'Found warning definitions with duplicate name: %s' % definition.name)
    _validate(definition)
    ret[definition.name] = definition
  return ret

def _populate_monorail_bug_default_fields(definitions, monorail_bug_default):
  """If default field value has been declared for monorail bug, run through all
  monorail bugs declared in all warning definitions and assign default
  value to fields which are empty

  Args:
    * definitions (list of warning.Definition)
    * monorail_bug_default (warning.MonorailBugDefault): contains the default
    value for some fields (namely, host and project) in warning.MonorailBug
    message.
  """
  for definition in definitions:
    for bug in definition.monorail_bug:
      bug.host = bug.host or monorail_bug_default.host
      bug.project = bug.project or monorail_bug_default.project

def _validate(definition):
  """Ensure the given warning definition is valid. ValueError will be
  raised otherwise. All conditions are documented in warning.proto.

  Args:
    * definition (warning.Definition proto)
  """
  if not re.match(r"^[A-Z][A-Z0-9]*(\_[A-Z0-9]+)*$", definition.name):
    raise ValueError(
      'Expect warning name to be all CAPS or num snake case. Actual: %s' % (
        definition.name))

  if definition.deadline:
    try:
      datetime.strptime(definition.deadline, '%Y-%m-%d')
    except ValueError:
      raise ValueError(
        'The deadline should be in YYYY-MM-DD format. Actual: %s' % (
          definition.deadline))

  for bug in definition.monorail_bug:
    err_msg_template = 'Field: %s is required; Got empty value'
    _require_non_zero_value(bug.host, err_msg_template % 'host')
    _require_non_zero_value(bug.project, err_msg_template % 'project')
    _require_non_zero_value(bug.id, err_msg_template % 'id')

def _require_non_zero_value(value, message):
  """Raise ValueError with message if the supplied value is a zero value
  """
  if not value:
    raise ValueError(message)