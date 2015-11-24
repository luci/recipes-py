from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
]

RETURN_SCHEMA = config.ReturnSchema(
  result=config.Single(int),
)


def RunSteps(api):
  api.step('bam', ['bingo'])
  # No return on purpose

def GenTests(api):
  yield (
      api.test('basic') +
      api.expect_exception('ValueError')
  )
