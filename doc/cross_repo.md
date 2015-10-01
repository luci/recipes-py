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

It is sometimes desirable to develop locally across repositories, for example,
to make a change in `build` and see what its effect on `build_internal` recipes
is.  Currently the way to do this is to manually update the `recipes.cfg` file
to point to your local repository.  So, for example, if you kept your `build`
repository in `/home/sally/chromium/build/` and were developing on the
branch `standpoor`, you could change your `build_internal` `recipes.cfg` to look
like this:
  
    api_version: 1
    project_id: "build_internal"
    recipes_path: ""
    deps {
      project_id: "build"
      url: "/home/sally/chromium/build/"
      branch: "standpoor"
      revision: "standpoor"
    }
    deps {
      project_id: "recipe_engine"
      url: "https://chromium.googlesource.com/external/github.com/luci/recipes-py.git"
      branch: "master"
      revision: "fe88a668a6cea70d2233c4e61be352fc1551d1ce"
    }

Note that `standpoor` for both the branch *and* the revision, so that the latest
commit on `build` is always used. (Only use this for development -- `revision`
should be a real revision hash)  It may be necessary to clobber `.recipe_deps`
when you change this, since detecting changed remotes is not supported.
