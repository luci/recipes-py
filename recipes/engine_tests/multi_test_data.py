"""Tests that step_data can accept multiple specs at once."""

DEPS = [
  'raw_io',
  'step',
]

def RunSteps(api):
  doge = api.step('doge',
      ['doge'], stdout=api.raw_io.output(), stderr=api.raw_io.output())
  assert doge.stdout == 'such stdout'
  assert doge.stderr == 'so stderring'

def GenTests(api):
  yield (
    api.test('basic') +
    api.step_data('doge',
      api.raw_io.stream_output('such stdout', stream='stdout'),
      api.raw_io.stream_output('so stderring', stream='stderr')))
