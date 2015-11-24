from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'recipe_engine/properties',
]

# Missing PROPERTIES on purpose

RETURN_SCHEMA = config.ReturnSchema(
  result=config.Single(int),
)


def RunSteps(api):
  return RETURN_SCHEMA(result=0)

def GenTests(api):
  yield (
      api.test('basic')
  )
