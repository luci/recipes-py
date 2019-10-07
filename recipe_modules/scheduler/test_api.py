# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (
    triggers as triggers_pb2)


class SchedulerTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, hostname=None, triggers=None):
    """Emulates scheduler module state.

    triggers must be None or a list of triggers_pb2.Trigger objects.
    """
    assert hostname is None or isinstance(hostname, basestring)
    assert not triggers or all(
        isinstance(t, triggers_pb2.Trigger) for t in triggers)
    ret = self.test(None)
    ret.properties.update(**{
      '$recipe_engine/scheduler': {
        'hostname': hostname,
        'triggers': [json_format.MessageToDict(t) for t in triggers or []],
      },
    })
    return ret
