# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import functools
import collections
import contextlib
import json

from recipe_engine import recipe_api
from recipe_engine import util as recipe_util
from recipe_engine import config_types


class JsonOutputPlaceholder(recipe_util.OutputPlaceholder):
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
  def __init__(self, api, add_json_log, name=None):
    self.raw = api.m.raw_io.output_text('.json')
    self.add_json_log = add_json_log
    super(JsonOutputPlaceholder, self).__init__(name=name)

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
      ret = JsonApi.loads(
          raw_data, object_pairs_hook=collections.OrderedDict)
      valid = True
    # TypeError is raised when raw_data is None, which can happen if the json
    # file was not created. We then correctly handle this as invalid result.
    except (ValueError, TypeError):  # pragma: no cover
      pass

    if self.add_json_log:
      key = self.label + ('' if valid else ' (invalid)')
      with contextlib.closing(recipe_util.StringListIO()) as listio:
        json.dump(ret, listio, indent=2, sort_keys=True)
      presentation.logs[key] = listio.lines

    return ret


class JsonApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(JsonApi, self).__init__(**kwargs)
    @functools.wraps(json.dumps)
    def dumps(*args, **kwargs):
      kwargs['sort_keys'] = True
      kwargs.setdefault('default', config_types.json_fixup)
      return json.dumps(*args, **kwargs)
    self.dumps = dumps

  @classmethod
  def loads(self, data, **kwargs):
    def strip_unicode(obj):
      if isinstance(obj, unicode):
        return obj.encode('utf-8', 'replace')

      if isinstance(obj, list):
        return map(strip_unicode, obj)

      if isinstance(obj, dict):
        new_obj = type(obj)(
            (strip_unicode(k), strip_unicode(v)) for k, v in obj.iteritems() )
        return new_obj

      return obj

    return strip_unicode(json.loads(data, **kwargs))

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
  def output(self, add_json_log=True, name=None):
    """A placeholder which will expand to '/tmp/file'."""
    return JsonOutputPlaceholder(self, add_json_log, name=name)

  # TODO(you): This method should be in the `file` recipe_module
  def read(self, name, path, add_json_log=True, output_name=None, **kwargs):
    """Returns a step that reads a JSON file."""
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
