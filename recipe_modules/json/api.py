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


def convert_trie_to_flat_paths(trie, prefix=None):
  # Cloned from webkitpy.layout_tests.layout_package.json_results_generator
  # so that this code can stand alone.
  result = {}
  for name, data in trie.iteritems():
    if prefix:
      name = prefix + "/" + name

    if len(data) and not "actual" in data and not "expected" in data:
      result.update(convert_trie_to_flat_paths(data, name))
    else:
      result[name] = data

  return result


class TestResults(object):
  def __init__(self, jsonish):
    self.raw = jsonish

    self.tests = convert_trie_to_flat_paths(jsonish.get('tests', {}))
    self.passes = {}
    self.unexpected_passes = {}
    self.failures = {}
    self.unexpected_failures = {}
    self.flakes = {}
    self.unexpected_flakes = {}

    for (test, result) in self.tests.iteritems():
      key = 'unexpected_' if result.get('is_unexpected') else ''
      actual_result = result['actual']
      data = actual_result
      if ' PASS' in actual_result:
        key += 'flakes'
      elif actual_result == 'PASS':
        key += 'passes'
        data = result
      else:
        key += 'failures'
      getattr(self, key)[test] = data

  def __getattr__(self, key):
    if key in self.raw:
      return self.raw[key]
    raise AttributeError("'%s' object has no attribute '%s'" %
                         (self.__class__, key))  # pragma: no cover


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
  # TODO(iannucci): The --output-json was a shortsighted bug. It should be
  # --json-output to generalize to '--<module>-<method>' convention, which is
  # used in multiple places in the recipe ecosystem.
  def __init__(self, name='output', flag='--output-json'):
    self.name = name
    self.flag = flag
    self.output_file = None
    super(JsonOutputPlaceholder, self).__init__()

  def render(self, test_data):
    items = [self.flag]
    if test_data is not None:
      items.append('/path/to/tmp/json')
    else:  # pragma: no cover
      json_output_fd, self.output_file = tempfile.mkstemp()
      os.close(json_output_fd)
      items.append(self.output_file)
    return items

  def step_finished(self, presentation, result_data, test_data):
    assert not hasattr(result_data, self.name)
    if test_data is not None:
      raw_data = json.dumps(test_data.pop(self.name, None))
    else:  # pragma: no cover
      assert self.output_file is not None
      with open(self.output_file, 'r') as f:
        raw_data = f.read()
      os.unlink(self.output_file)

    valid = False
    try:
      setattr(result_data, self.name, json.loads(raw_data))
      valid = True
    except ValueError:  # pragma: no cover
      pass

    key = 'json.' + self.name + ('' if valid else ' (invalid)')
    listio = StringListIO()
    json.dump(getattr(result_data, self.name), listio, indent=2, sort_keys=True)
    listio.close()
    presentation.logs[key] = listio.lines


class TestResultsOutputPlaceholder(JsonOutputPlaceholder):
  def __init__(self):
    super(TestResultsOutputPlaceholder, self).__init__(
      name='test_results', flag='--json-test-results')

  def step_finished(self, presentation, result_data, test_data):
    super(TestResultsOutputPlaceholder, self).step_finished(
      presentation, result_data, test_data)
    result_data.test_results = TestResults(result_data.test_results)


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

  @staticmethod
  def test_results():
    """A placeholder which will expand to '--json-test-results /tmp/file'.

    The test_results will be an instance of the TestResults class.
    """
    return TestResultsOutputPlaceholder()

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

