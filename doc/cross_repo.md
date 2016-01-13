# Cross-repo development in recipes

At the time of writing, there are three repositories containing recipes and
recipe modules, soon to be more.  Repositories declare their relationships to
each other in a file called `recipes.cfg`, usually in the `infra/config`
directory from the repository root.  For example:

    api_version: 1
    project_id: "build_internal"
    recipes_path: ""
    deps {
      project_id: "build"
      url: "https://chromium.googlesource.com/chromium/tools/build"
      branch: "master"
      revision: "09cee0ae226949923db058cb21e98a42d7d29f11"
    }
    deps {
      project_id: "recipe_engine"
      url: "https://chromium.googlesource.com/external/github.com/luci/recipes-py.git"
      branch: "master"
      revision: "fe88a668a6cea70d2233c4e61be352fc1551d1ce"
    }

`project_id` is the LUCI-config identifier for the project.  `recipes_path` is
the path from the root of the repository to the location of the `recipes` and
`recipe_modules` directories.  This collection of recipes-related things in a
repository is called a *recipe package*.

There are two `deps` entries in this file.  There always has to be an entry for
the `recipe_engine` project, which pins the version of the engine that is used,
and all projects in a particular dependency graph must agree on the engine
revision (in fact, they must agree on the revision of any shared dependency).

The `recipes.py` tool, which goes alongside the `recipes` and `recipe_modules`
directories, can be used to interact with the dependencies of a recipe package.

    $ ./recipes.py fetch

fetches the whole dependency graph into the `.recipe_deps` directory (again
alongside `recipes` and `recipe_modules`) at the pinned revisions.  This is done
automatically in most cases, but can be helpful if you want to poke around the
graph.

    $ ./recipes.py roll

updates the dependencies in `recipes.cfg`, following the specified `branch`
forward.  `roll` takes *as small a step forward as possible*, so you have to run
it multiple times if you want to roll farther.  This is so that it is possible,
for example, to tell at which point the simulation tests broke.

The `recipes.py` tool has several other modes for working with a recipe package,
which are not covered here, but look at `recipes.py --help`.

## Local development

When locally developing recipes, it is oftentimes desirable to observe the
effect that your local changes will have on other repositories. This can be done
by using recipe engine *local project overrides* command-line flags (`-O`).

Local project overrides allow the user to redirect a project's checkout to a
local path during execution. A developer would run the downstream project,
overriding the one or more upstream projects under development.

For example, to make a change in `build` and see what its effect on
`build_internal` recipes, one would execute `build_internal`'s recipe,
overriding its `build` project to point to the local path.

    $ ./recipes.py -O build=/path/to/build simulation_test train

This would simulate and train `build_internal` recipes, using the local `build`
checkout instead of the one configured in `build_internal`'s `recipes.cfg`.

In the case that you want to test local changes to the recipe engine itself,
the workflow is a little different, for technical reasons.  Let's say you have
a `recipes-py` checkout in `/b/recipes-py`, which you've modified, and you
want to see its effects on the repository `/b/build`.  Run:

    $ /b/recipes-py/recipes.py --package /b/build/infra/config/recipes.cfg \
      -O recipe_engine=/b/recipes-py simulation_test

Running `/b/recipes-py/recipes.py` uses the modified engine, however without
the `-O` package override option, it would still use core modules pinned in
`recipes.cfg`.
