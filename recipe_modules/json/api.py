# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Methods for producing and consuming JSON."""

import functools
import collections
import contextlib
import json

from recipe_engine import recipe_api
from recipe_engine import util as recipe_util
from recipe_engine import config_types


@functools.wraps(json.dumps)
def dumps(*args, **kwargs):
  kwargs['sort_keys'] = True
  kwargs.setdefault('default', config_types.json_fixup)
  return json.dumps(*args, **kwargs)


@functools.wraps(json.loads)
def loads(data, **kwargs):
  return recipe_util.fix_json_object(json.loads(data, **kwargs))


class JsonOutputPlaceholder(recipe_util.OutputPlaceholder):
  """JsonOutputPlaceholder is meant to be a placeholder object which, when added
  to a step's cmd list, will be replaced by the recipe engine with the path to a
  temporary file (e.g. /tmp/tmp4lp1qM) which will exist only for the duration of
  the step. Create a JsonOutputPlaceholder by calling the 'output()' method of
  the JsonApi.

  The step is expected to write JSON data to this file, and when the step is
  finished, the file will be read and the JSON parsed back into the recipe, and
  will be available as part of the step result.

  Example:
    result = api.step('step name',
      ['write_json_to_file.sh', api.json.output()])
    # `result.json.output` is the parsed JSON value.

  See the example recipe (./examples/full.py) for some more uses.
  """
  def __init__(self, api, add_json_log, name=None, leak_to=None):
    assert add_json_log in (True, False, 'on_failure'), (
        'add_json_log=%r' % add_json_log)
    self.raw = api.m.raw_io.output_text('.json', leak_to=leak_to)
    self.add_json_log = add_json_log
    super(JsonOutputPlaceholder, self).__init__(name=name)

  @property
  def backing_file(self):
    return self.raw.backing_file

  def render(self, test):
    return self.raw.render(test)

  def result(self, presentation, test):
    # Save name before self.raw.result() deletes it.
    backing_file = self.backing_file
    raw_data = self.raw.result(presentation, test)
    if raw_data is None:
      if self.add_json_log in (True, 'on_failure'):
        presentation.logs[self.label + ' (read error)'] = [
          'JSON file was missing or unreadable:',
          '  ' + backing_file,
        ]
      return None

    valid = False
    invalid_error = ''
    ret = None
    try:
      ret = loads(raw_data, object_pairs_hook=collections.OrderedDict)
      valid = True
    except ValueError as ex:  # pragma: no cover
      invalid_error = str(ex)

    if self.add_json_log is True or (
        self.add_json_log == 'on_failure' and presentation.status != 'SUCCESS'):
      if valid:
        with contextlib.closing(recipe_util.StringListIO()) as listio:
          json.dump(ret, listio, indent=2, sort_keys=True)
        presentation.logs[self.label] = listio.lines
      else:
        presentation.logs[self.label + ' (invalid)'] = raw_data.splitlines()
        presentation.logs[self.label + ' (exception)'] = (
          invalid_error.splitlines())

    return ret


class JsonApi(recipe_api.RecipeApi):
  @staticmethod
  def dumps(*args, **kwargs):
    """Works like `json.dumps`."""
    return dumps(*args, **kwargs)

  @staticmethod
  def loads(data, **kwargs):
    """Works like `json.loads`, but:
      * strips out unicode objects (replacing them with utf8-encoded str
        objects).
      * replaces 'int-like' floats with ints. These are floats whose magnitude
        is less than (2**53-1) and which don't have a decimal component.
    """
    return loads(data, **kwargs)

  def is_serializable(self, obj):
    """Returns True if the object is JSON-serializable."""
    try:
      self.dumps(obj)
      return True
    except Exception:
      return False

  @recipe_util.returns_placeholder
  def input(self, data):
    """A placeholder which will expand to a file path containing <data>."""
    return self.m.raw_io.input_text(self.dumps(data), '.json')

  @recipe_util.returns_placeholder
  def output(self, add_json_log=True, name=None, leak_to=None):
    """A placeholder which will expand to '/tmp/file'.

    If leak_to is provided, it must be a Path object. This path will be used in
    place of a random temporary file, and the file will not be deleted at the
    end of the step.

    Args:
      * add_json_log (True|False|'on_failure') - Log a copy of the output json
        to a step link named `name`. If this is 'on_failure', only create this
        log when the step has a non-SUCCESS status.
    """
    return JsonOutputPlaceholder(self, add_json_log, name=name, leak_to=leak_to)

  def read(self, name, path, add_json_log=True, output_name=None, **kwargs):
    """Returns a step that reads a JSON file.

    This method is deprecated. Use file.read_json instead.
    """
    return self.m.python.inline(
        name,
        """
        import shutil
        import sys
        shutil.copy(sys.argv[1], sys.argv[2])
        """,
        args=[path,
              self.output(add_json_log=add_json_log, name=output_name)],
        add_python_log=False,
        **kwargs
    )
