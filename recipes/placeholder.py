# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
  'step',
  'properties',
]

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct

from PB.recipe_engine import result as result_pb2
from PB.recipes.recipe_engine.placeholder import InputProps, Step
from PB.go.chromium.org.luci.buildbucket.proto.common import Status

PROPERTIES = InputProps


def fakeSleep(api, duration):
  # TODO(iannucci): Once https://chromium-review.googlesource.com/c/3346660
  # lands, this function won't be necessary, but adding this for now due to
  # production freeze.
  if not api._test_data.enabled:  # pragma: no cover
    import gevent
    gevent.sleep(duration)


def RunSteps(api, properties):
  def handlePres(result, step_pb):
    pres = result.presentation

    pres.step_text = step_pb.step_text
    for name, link in step_pb.links.items():
      pres.links[name] = link
    for name, log in step_pb.logs.items():
      pres.logs[name] = log.splitlines()

    pres.status = {
      Status.FAILURE: 'FAILURE',
      Status.INFRA_FAILURE: 'EXCEPTION',
      Status.CANCELED: 'CANCELED',
    }.get(step_pb.status, 'SUCCESS')
    pres.had_timeout = step_pb.timeout
    pres.was_canceled = step_pb.canceled

    pres.properties = json_format.MessageToDict(step_pb.set_properties)

  def processStep(step):
    if step.children:
      with api.step.nest(step.name) as pres:
        handlePres(pres, step)

        if step.duration_secs > 0:
          fakeSleep(api, step.duration_secs)

        for child in step.children:
          processStep(child)
    else:
      result = api.step(step.name, cmd=None)
      handlePres(result, step)
      if step.duration_secs > 0:
        fakeSleep(api, step.duration_secs)

  if properties.steps:
    for step in properties.steps:
      processStep(step)
  else:
    processStep(Step(name='hello world', duration_secs=10))

  return result_pb2.RawResult(status=properties.status)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'presentation',
      api.properties(InputProps(
          steps = [
            Step(
                name='cool',
                step_text='text',
                logs={'log': 'multiline\ndata'},
                links={'link': 'https://example.com'},
                status=Status.FAILURE,
                set_properties=json_format.ParseDict({
                  "generic": "stuff",
                  "key": 100,
                }, Struct()),
                canceled=True,
                timeout=True,
            ),
            Step(
                name='parent',
                duration_secs=10,
                children=[
                  Step(name='a'),
                  Step(name='b'),
                ]
            )
          ],
          status=Status.INFRA_FAILURE,
      ))
  )
