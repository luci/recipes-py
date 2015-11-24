from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'recipe_engine/properties',
]

PROPERTIES = {
    'to_pass': Property(),
}

RETURN_SCHEMA = config.ReturnSchema(
    result=config.Single(int),
)

def RunSteps(api, to_pass):
  res = api.depend_on('engine_tests/depend_on/bottom', {'number': to_pass})
  return RETURN_SCHEMA(result=res['number_times_two'])

def GenTests(api):
  yield (
      api.test('basic') +
      api.properties(to_pass=3) +
      api.depend_on('engine_tests/depend_on/bottom', {'number': 3}, {'number_times_two': 6})
  )
