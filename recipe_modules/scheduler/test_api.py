# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from past.builtins import basestring

from google.protobuf import json_format

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (
    triggers as triggers_pb2)


class SchedulerTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, hostname=None, job_id=None, invocation_id=None, triggers=None):
    """Emulates scheduler module state.

    triggers must be None or a list of triggers_pb2.Trigger objects.
    """
    assert hostname is None or isinstance(hostname, basestring)
    assert job_id is None or isinstance(job_id, basestring)
    assert invocation_id is None or isinstance(invocation_id, int)
    assert not triggers or all(
        isinstance(t, triggers_pb2.Trigger) for t in triggers)

    prop = {}
    if hostname is not None:
      prop['hostname'] = hostname
    if job_id is not None:
      prop['job'] = job_id
    if invocation_id is not None:
      prop['invocation'] = str(invocation_id)
    if triggers:
      prop['triggers'] = [json_format.MessageToDict(t) for t in triggers]

    ret = self.test(None)
    ret.properties['$recipe_engine/scheduler'] = prop
    return ret
