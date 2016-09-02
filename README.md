# Recipes

Recipes are a domain-specific language (embedded in python) for specifying
sequences of subprocess calls in a cross-platform and testable way.

* [User guide](doc/user_guide.md)
* Recipes: [public](https://chromium.googlesource.com/chromium/tools/build.git/+/master/scripts/slave/recipes/);
  [internal](https://chrome-internal.googlesource.com/chrome/tools/build_limited/scripts/slave/+/master/recipes/).
* Recipe modules: [public](https://chromium.googlesource.com/chromium/tools/build.git/+/master/scripts/slave/recipe_modules/);
  [internal](https://chrome-internal.googlesource.com/chrome/tools/build_limited/scripts/slave/+/master/recipe_modules/).

# Files

*   `README.md`

    This file!

*   `bootstrap/`

    Bootstrapping and vendoring related code.

*   `doc/`

    Documentation for the recipe engine (including this file!). Also includes
    `doc/recipes.py`, which is a file you can include in your repository to
    start using recipes. See the [design doc](doc/design_doc.md) for more
    detailed design information about the recipe engine.

*   `infra/`

    Chrome infra config files.

*   `recipes.py`

    The main entry point to the recipe engine. It has many subcommands and
    flags; run `recipes.py -h` to see them.

*   `recipes/`

    Recipes in the recipe engine. These are either example recipes, or recipes
    which are used to test the engine (see
    [run_test.py](recipe_engine/unittests/run_test.py) to see these run)

*   `recipe_modules/`

    Built in recipe modules. These are very useful when writing recipes; take a
    look in there, and look at their `example.py` files.

*   `recipe_engine/`

    The core functionality of the recipe engine. Noteworthy files include:
    * `package.proto` -- The protobuf file which defines the format of a
    `recipes.cfg` file.
    * `third_party/` -- third_party code which is vendored into the recipe
      engine.
    * `recipe_api.py` -- The api exposed to a recipe module.
    * `unittests` -- Unittests for the engine.

    There are also several files which correspond to a subcommand of recipes.py;
    `depgraph`, `run`, and `autoroll` are some examples.

*   `unittests/`

    Somewhat poorly named, these are higher level integration tests.

# Contributing

  * Sign the [Google CLA](https://cla.developers.google.com/clas).
  * Make sure your `user.email` and `user.name` are configured in `git config`.

Run the following to setup the code review tool and create your first review:

    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git $HOME/src/depot_tools
    export PATH="$PATH:$HOME/src/depot_tools"
    git checkout -b work origin/master

    # hack hack

    git commit -a -m "This is awesome\nR=joe@example.com"
    # This will ask for your Google Account credentials.
    git cl upload -s
    # Wait for LGTM over email.
    # Check the commit queue box in codereview website.
    # Wait for the change to be tested and landed automatically.

Use `git cl help` and `git cl help <cmd>` for more details.
