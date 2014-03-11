DEPS = [
  'path',
  'platform',
  'step',
  ]

def GenSteps(api):
  # New way of doing things
  yield (api.step('step1',
                  ['/bin/echo', str(api.path['slave_build'].join('foo'))]))
  # Deprecated way of doing things.
  # TODO(pgervais,crbug.com/323280) remove this api
  yield (api.step('step2',
                  ['/bin/echo', str(api.path.slave_build('foo'))]))

def GenTests(api):
  # These two lines are for code coverage.
  api.path.slave_build('foo')  # TODO(pgervais,crbug.com/323280) remove this api
  api.path['slave_build'].join('foo')
  yield(api.test('basic'))
