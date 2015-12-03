from recipe_engine.recipe_api import Property

DEPS = [
  'step',
  'properties',
  'python',
]

PROPERTIES = {
  'from_recipe': Property(kind=bool, default=False),
  'attribute': Property(kind=bool, default=False),
  'module': Property(kind=bool, default=False),
}

def RunSteps(api, from_recipe, attribute, module):
  # We test on the python module because it's a RecipeApi, not a RecipeApiPlain.
  if from_recipe:
    api.missing_module('baz')
  if attribute:
    api.python.missing_method('baz')
  if module:
    api.python.m.missing_module('baz')

def GenTests(api):
  yield (
      api.test('from_recipe') +
      api.properties(from_recipe=True) +
      api.expect_exception('ModuleInjectionError'))

  yield (
      api.test('attribute') +
      api.properties(attribute=True) +
      api.expect_exception('AttributeError'))

  yield (
      api.test('module') +
      api.properties(module=True) +
      api.expect_exception('ModuleInjectionError'))
