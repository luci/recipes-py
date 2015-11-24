from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'recipe_engine/properties',
]

PROPERTIES = {}

# Missing a RETURN_SCHEMA on purpose

def RunSteps(api):
  pass

def GenTests(api):
  yield (
      api.test('basic')
  )
