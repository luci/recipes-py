# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import collections
import contextlib
import json

from slave import recipe_api
from slave import recipe_util
from slave import recipe_config_types


class JsonOutputPlaceholder(recipe_util.Placeholder):
  """JsonOutputPlaceholder is meant to be a placeholder object which, when added
  to a step's cmd list, will be replaced by annotated_run with the path to a
  temporary file (e.g. /tmp/tmp4lp1qM) which will exist only for the duration of
  the step. If the script requires a flag (e.g. --output-json /path/to/file),
  you must supply that flag yourself in the cmd list.

  This placeholder can be optionally added when you use the Steps.step()
  method in this module.

  FIXME
  After the termination of the step, this file is expected to contain a valid
  JSON document, which will be set as the json.output for that step in the
  step_history OrderedDict passed to your recipe generator.
  """
  def __init__(self, api, add_json_log):
    self.raw = api.m.raw_io.output('.json')
    self.add_json_log = add_json_log
    super(JsonOutputPlaceholder, self).__init__()

  @property
  def backing_file(self):
    return self.raw.backing_file

  def render(self, test):
    return self.raw.render(test)

  def result(self, presentation, test):
    raw_data = self.raw.result(presentation, test)

    valid = False
    ret = None
    try:
      ret = json.loads(raw_data, object_pairs_hook=collections.OrderedDict)
      valid = True
    # TypeError is raised when raw_data is None, which can happen if the json
    # file was not created. We then correctly handle this as invalid result.
    except (ValueError, TypeError):  # pragma: no cover
      pass

    if self.add_json_log:
      key = self.name + ('' if valid else ' (invalid)')
      with contextlib.closing(recipe_util.StringListIO()) as listio:
        json.dump(ret, listio, indent=2, sort_keys=True)
      presentation.logs[key] = listio.lines

    return ret


class JsonApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(JsonApi, self).__init__(**kwargs)
    self.loads = json.loads
    @functools.wraps(json.dumps)
    def dumps(*args, **kwargs):
      kwargs['sort_keys'] = True
      kwargs.setdefault('default', recipe_config_types.json_fixup)
      return json.dumps(*args, **kwargs)
    self.dumps = dumps

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
    return self.m.raw_io.input(self.dumps(data), '.json')

  @recipe_util.returns_placeholder
  def output(self, add_json_log=True):
    """A placeholder which will expand to '/tmp/file'."""
    return JsonOutputPlaceholder(self, add_json_log)

  # TODO(you): This method should be in the `file` recipe_module
  def read(self, name, path, **kwargs):
    """Returns a step that reads a JSON file."""
    return self.m.python.inline(
        name,
        """
        import shutil
        import sys
        shutil.copy(sys.argv[1], sys.argv[2])
        """,
        args=[path, self.output()],
        add_python_log=False,
        **kwargs
    )

  def property_args(self):
    """Return --build-properties and --factory-properties arguments. LEGACY!

    Since properties is the merge of build_properties and factory_properties,
    pass the merged dict as both arguments.

    It's vastly preferable to have your recipe only pass the bare minimum
    of arguments to steps. Passing property objects obscures the data that
    the script actually consumes from the property object.
    """
    prop_str = self.dumps(dict(self.m.properties.legacy()))
    return [
      '--factory-properties', prop_str,
      '--build-properties', prop_str
    ]
