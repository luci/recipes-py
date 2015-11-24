from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'recipe_engine/properties',
]

PROPERTIES = {}

RETURN_SCHEMA = config.ReturnSchema(
    result=config.Single(int),
)

def RunSteps(api):
  res = api.depend_on('engine_tests/depend_on/bottom', {'number': 'lalala'})
  return RETURN_SCHEMA(result=res['number_times_two'])

def GenTests(api):
  yield (
      api.test('basic') +
      api.properties() +
      api.expect_exception('TypeError')
  )
