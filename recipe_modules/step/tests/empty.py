# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import StepSuccess, LogEquals, StepTextEquals
from recipe_engine.post_process import StepException, StepFailure
from recipe_engine.post_process import DropExpectation

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'step',
]


def RunSteps(api):
  api.step.empty('hello', step_text='stuff', stdout_text='other\nstuff')

  api.step.empty('multi hello', stdout_text=['multi', 'line'])

  try:
    api.step.empty('bye', status=api.step.FAILURE)
    assert False, 'unreachable'  # pragma: no cover
  except api.step.StepFailure:
    pass

  try:
    api.step.empty('bigfail', status=api.step.INFRA_FAILURE)
    assert False, 'unreachable'  # pragma: no cover
  except api.step.StepFailure:
    pass

  api.step.empty('quiet fail', status=api.step.FAILURE, raise_on_failure=False)

def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(StepSuccess, 'hello'),
      api.post_process(LogEquals, 'hello', 'stdout', 'other\nstuff'),
      api.post_process(StepTextEquals, 'hello', 'stuff'),

      api.post_process(StepSuccess, 'multi hello'),
      api.post_process(LogEquals, 'multi hello', 'stdout', 'multi\nline'),

      api.post_process(StepException, 'bigfail'),

      api.post_process(StepFailure, 'quiet fail'),

      api.post_process(DropExpectation),
  )
