DEPS = ['step']

def RunSteps(api):
  api.step('Run missing command', ['missing_command'])

def GenTests(api):
  yield api.test('basic')
