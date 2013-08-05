# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import json
import os
import tempfile

from cStringIO import StringIO

from slave import recipe_api

class StringListIO(object):
  def __init__(self):
    self.lines = [StringIO()]

  def write(self, s):
    while s:
      i = s.find('\n')
      if i == -1:
        self.lines[-1].write(s)
        break
      self.lines[-1].write(s[:i])
      self.lines[-1] = self.lines[-1].getvalue()
      self.lines.append(StringIO())
      s = s[i+1:]

  def close(self):
    if not isinstance(self.lines[-1], basestring):
      self.lines[-1] = self.lines[-1].getvalue()


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

  def step_finished(self, presentation, result_data, test_data):
    assert not hasattr(result_data, 'output')
    if test_data is not None:
      raw_data = json.dumps(test_data.pop('output', None))
    else:  # pragma: no cover
      assert self.output_file is not None
      with open(self.output_file, 'r') as f:
        raw_data = f.read()
      os.unlink(self.output_file)

    valid = False
    try:
      result_data.output = json.loads(raw_data)
      valid = True
    except ValueError:  # pragma: no cover
      pass

    key = 'json.output' + ('' if valid else ' (invalid)')
    listio = StringListIO()
    json.dump(result_data.output, listio, indent=2, sort_keys=True)
    listio.close()
    presentation.logs[key] = listio.lines


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
    return recipe_api.InputDataPlaceholder(self.dumps(data), '.json')

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

