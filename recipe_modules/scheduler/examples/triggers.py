# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating reading triggers of the current build."""

from __future__ import annotations

import json

from google.protobuf import json_format

from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (
    triggers as triggers_pb2)

DEPS = [
  'json',
  'scheduler',
  'step',
]

def RunSteps(api):
  pres = api.step(name='triggers', cmd=None).presentation
  pres.logs['triggers'] = api.json.dumps(
      [json_format.MessageToDict(t) for t in api.scheduler.triggers],
      sort_keys=True,
      indent=2,
  ).splitlines()

  if api.scheduler.triggers and api.scheduler.triggers[0].gitiles.repo:
    pres.logs['first_repo'] = [api.scheduler.triggers[0].gitiles.repo]


def GenTests(api):
  yield (
    api.test('unset')
  )
  yield (
    api.test('gitiles') +
    api.scheduler(
      triggers=[
        triggers_pb2.Trigger(
          id='a',
          gitiles=dict(
            repo='https://chromium.googlesource.com/chomium/src',
            ref='refs/heads/main',
            revision='a' * 40,
          ),
        ),
        triggers_pb2.Trigger(
          id='b',
          gitiles=dict(
            repo='https://chromium.googlesource.com/chomium/src',
            ref='refs/heads/main',
            revision='b' * 40,
          ),
        ),
      ],
    )
  )

  bb_trigger = triggers_pb2.BuildbucketTrigger(tags=['a:b'])
  bb_trigger.properties.update({'foo': 'bar'})
  yield (
    api.test('various') +
    api.scheduler(
      triggers=[
        triggers_pb2.Trigger(id='a', cron=dict(generation=123)),
        triggers_pb2.Trigger(id='b', webui=dict()),
        triggers_pb2.Trigger(id='c', buildbucket=bb_trigger),
      ],
    )
  )
