# Recipes

Recipes are a domain-specific language (embedded in python) for specifying
sequences of subprocess calls in a cross-platform and testable way.

They allow writing build flows which integrate with the rest of LUCI.

Documentation for the recipe engine (including this file!). Take a look at
the [user guide](doc/user_guide.md) for some hints on how to get started.
See the [implementation details doc](doc/implementation_details.md) for more
detailed implementation information about the recipe engine.

* [User guide](doc/user_guide.md) - hints on how to get started
* [Recipe engine module docs](README.recipes.md) - Documentation on the recipe
  modules which are available in this repo.
* [Implementation details](doc/implementation_details.md) on how recipes
  operate.

# Contributing

  * Sign the [Google CLA](https://cla.developers.google.com/clas).
  * Make sure your `user.email` and `user.name` are configured in `git config`.

Run the following to setup the code review tool and create your first review:

    # Get `depot_tools` in $PATH if you don't have it
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git $HOME/src/depot_tools
    export PATH="$PATH:$HOME/src/depot_tools"

    # Check out the recipe engine repo
    git clone https://chromium.googlesource.com/infra/luci/recipes-py $HOME/src/recipes-py

    # make your change
    cd $HOME/src/recipes-py
    git new-branch cool_feature
    # hack hack
    git commit -a -m "This is awesome"

    # This will ask for your Google Account credentials.
    git cl upload -s -r joe@example.com
    # Wait for approval over email.
    # Click "Submit to CQ" button or ask reviewer to do it for you.
    # Wait for the change to be tested and landed automatically.

Use `git cl help` and `git cl help <cmd>` for more details.
