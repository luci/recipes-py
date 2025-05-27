# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import message
from google.protobuf import json_format as jsonpb

from recipe_engine import recipe_test_api

class ContextTestApi(recipe_test_api.RecipeTestApi):
  def luci_context(self, **section_pb_values):
    """Sets the LUCI_CONTEXT for this test case.

    Args:
      * section_pb_values(Dict[str, message.Message]): A mapping of section_key
      to the proto value for that section.
    """
    ret = self.test(None)
    for section_key, pb_val in section_pb_values.items():
      if not isinstance(pb_val, message.Message): # pragma: no cover
          raise ValueError(
              'Expected section value in LUCI_CONTEXT to be proto message;'
              'Got: %r=%r (type %r)' % (section_key, pb_val, type(pb_val)))
      ret.luci_context[section_key] = jsonpb.MessageToDict(pb_val)
    return ret

  @property
  def realm(self):
    """Placeholder for realm property."""
    return None
