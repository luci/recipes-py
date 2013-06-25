# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import json
import os
import tempfile

from slave import recipe_api


class JsonOutputPlaceholder(recipe_api.Placeholder):
  """JsonOutputPlaceholder is meant to be a placeholder object which, when added
  to a step's cmd list, will be replaced by annotated_run with the command
  parameters --output-json /path/to/file during the evaluation of your recipe
  generator.

  This placeholder can be optionally added when you use the Steps.step()
  method in this module.

  After the termination of the step, this file is expected to contain a valid
  JSON document, which will be set as the json_output for that step in the
  step_history OrderedDict passed to your recipe generator.
  """
  def __init__(self):
    self.output_file = None
    super(JsonOutputPlaceholder, self).__init__()

  def render(self, test_data):
    items = ['--output-json']
    if test_data is not None:
      items.append('/path/to/tmp/json')
    else:  # pragma: no cover
      json_output_fd, self.output_file = tempfile.mkstemp()
      os.close(json_output_fd)
      items.append(self.output_file)
    return items

  def step_finished(self, stream, result_data, test_data):
    assert not hasattr(result_data, 'output')
    if test_data is not None:
      result_data.output = test_data.pop('output', None)
    else:  # pragma: no cover
      assert self.output_file is not None
      with open(self.output_file, 'r') as f:
        raw_data = f.read()
      try:
        result_data.output = json.loads(raw_data)
        stream.emit('step returned json data: """\n%s\n"""' %
                    (result_data.output,))
      except ValueError:
        stream.emit('step had invalid json data: """\n%s\n"""' %
                    raw_data)
      os.unlink(self.output_file)


class JsonInputPlaceholder(recipe_api.Placeholder):
  """JsonInputPlaceholder is meant to be a non-singleton object which, when
  added to a step's cmd list, will be replaced by annotated_run with a
  /path/to/json file during the evaluation of your recipe generator.

  The file will have the json-string passed to __init__, and is guaranteed to
  exist solely for the duration of the step.

  Multiple instances of thif placeholder can occur in a step's command, and
  each will be serialized to a different input file.
  """
  __slots__ = ['json_string']

  def __init__(self, json_string):
    assert isinstance(json_string, basestring)
    self.json_string = json_string
    self.input_file = None
    super(JsonInputPlaceholder, self).__init__()

  def render(self, test_data):
    if test_data is not None:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      return [self.json_string]
    else:  # pragma: no cover
      json_input_fd, self.input_file = tempfile.mkstemp()
      os.write(json_input_fd, self.json_string)
      os.close(json_input_fd)
      return [self.input_file]

  def step_finished(self, stream, step_result, test_data):
    if test_data is None:  # pragma: no cover
      os.unlink(self.input_file)


class JsonApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(JsonApi, self).__init__(**kwargs)
    self.loads = json.loads
    @functools.wraps(json.dumps)
    def dumps(*args, **kwargs):
      kwargs['sort_keys'] = True
      return json.dumps(*args, **kwargs)
    self.dumps = dumps

  def input(self, data):
    """A placeholder which will expand to a file path containing <data>."""
    return JsonInputPlaceholder(self.dumps(data))

  @staticmethod
  def output():
    """A placeholder which will expand to '--output-json /tmp/file'."""
    return JsonOutputPlaceholder()

  def property_args(self):
    """Return --build-properties and --factory-properties arguments. LEGACY!

    Since properties is the merge of build_properties and factory_properties,
    pass the merged dict as both arguments.

    It's vastly preferable to have your recipe only pass the bare minimum
    of arguments to steps. Passing property objects obscures the data that
    the script actually consumes from the property object.
    """
    prop_str = self.dumps(dict(self.m.properties))
    return [
      '--factory-properties', prop_str,
      '--build-properties', prop_str
    ]

