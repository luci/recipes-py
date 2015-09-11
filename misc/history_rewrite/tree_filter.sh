# if third_party/recipe_engine/ exists
#   save third_party/recipe_engine
#   nuke
#   mv third_party/recipe_engine/* -> root
# else
#   save <all_related_files>
#   nuke
#   mv scripts/tools/* -> root
#   mv scripts/slave/* -> root
#   mv scripts/common/* -> root
#   mv third_party -> root

STAGING=$HOME/STAGING

function move_modules() {
  mkdir -p "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/example" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/generator_script" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/json" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/math_utils" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/path" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/platform" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/properties" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/python" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/raw_io" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/step" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/step_history" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/time" "$STAGING/recipe_modules"
  mv "scripts/slave/recipe_modules/uuid" "$STAGING/recipe_modules/"
}


if [[ -d third_party/recipe_engine ]]
then
  mv third_party/recipe_engine/* $STAGING
  mv doc.py $STAGING
  mv inspect_config.py $STAGING
  mv unittests/* "$STAGING/unittests"
  mv "$STAGING/main.py" "$STAGING/run.py"
  mv "$STAGING/expect_tests" "$STAGING/third_party"
  move_modules
else
  mv "scripts/common/python26_polyfill.py" "$STAGING/python26_polyfill.py"
  mv "scripts/slave/README.recipes.md" "$STAGING/README.md"
  mv "scripts/slave/annotated_checkout.py" "$STAGING/annotated_checkout.py"
  mv "scripts/slave/annotated_run.py" "$STAGING/run.py"
  mv "scripts/slave/field_composer.py" "$STAGING/field_composer.py"
  mv "scripts/slave/recipe_api.py" "$STAGING/recipe_api.py"
  mv "scripts/slave/recipe_config.py" "$STAGING/config.py"
  mv "scripts/slave/recipe_configs_util.py" "$STAGING/config.py"
  mv "scripts/slave/recipe_config_types.py" "$STAGING/config_types.py"
  mv "scripts/slave/recipe_loader.py" "$STAGING/loader.py"

  move_modules

  mv "scripts/slave/recipe_test_api.py" "$STAGING/recipe_test_api.py"
  mv "scripts/slave/recipe_universe.py" "$STAGING/recipe_universe.py"
  mv "scripts/slave/recipe_util.py" "$STAGING/util.py"

  mv "scripts/slave/unittests/recipe_lint.py" "$STAGING/lint_test.py"
  mv "scripts/slave/unittests/recipe_lint_test.py" "$STAGING/lint_test.py"
  mv "scripts/slave/unittests/recipe_simulation_test.py" "$STAGING/simulation_test.py"
  mv "scripts/slave/unittests/recipes_test.py" "$STAGING/simulation_test.py"

  mkdir -p "$STAGING/unittests"
  mv "scripts/slave/unittests/__init__.py" "$STAGING/unittests/__init__.py"
  mv "scripts/slave/unittests/annotated_run_test.py" "$STAGING/unittests/annotated_run_test.py"
  mv "scripts/slave/unittests/recipe_configs_test.py" "$STAGING/unittests/recipe_configs_test.py"
  mv "scripts/slave/unittests/recipe_util_test.py" "$STAGING/unittests/recipe_util_test.py"
  mv "scripts/slave/unittests/test_env.py" "$STAGING/unittests/test_env.py"

  mv "scripts/tools/inspect_recipe_config.py" "$STAGING/inspect_config.py"
  mv "scripts/tools/show_me_the_modules.py" "$STAGING/doc.py"
  mv "scripts/tools/unittests/show_me_the_modules_test.py" "$STAGING/unittests/doc_test.py"

  mkdir "$STAGING/third_party"
  mv "scripts/common/annotator.py" "$STAGING/third_party/annotator.py"
  mv "third_party/infra" "$STAGING/third_party/infra"
  mv "scripts/slave/unittests/expect_tests" "$STAGING/third_party"
fi

rm -rf .??* *
mkdir recipe_engine
mv $STAGING/* recipe_engine

mv recipe_engine/README.md .
mv recipe_engine/recipes.py .
mv recipe_engine/recipe_modules .
mv recipe_engine/infra .
mv recipe_engine/doc .

true
