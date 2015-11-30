"""Tests that step_data can accept multiple specs at once."""

DEPS = [
  'step',
]

def RunSteps(api):
  raise TypeError("BAD DOGE")

def GenTests(api):
  yield (
    api.test('basic') +
    api.expect_exception('TypeError')
  )
