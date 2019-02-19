# Recipe engine implementation details

This doc covers implementation details of the recipe engine and its processes.
Read this if you want to understand/modify how the recipes as a system work. For
general recipe developement, please see [user_guide.md](./user_guide.md).

[TOC]


## Loading

This section talks about how the recipe engine gets from the the recipes.py
command invocation to the point where it begins executing the recipe.


### Repo configuration

Recipes have a bit of an interesting multi-step loading process, though it has
gotten simpler over the years.

Every recipe repo has at least two things:
  * A `recipes.py` script (which is a literal copy of [recipes.py]).
  * A `recipes.cfg` config file located at `//infra/config/recipes.cfg`
    * (The hard-coded location is possibly not ideal, but it does keep things
      simple.)
    * This cfg file conforms to [recipes_cfg.proto], but also is parsed by
      [simple_cfg.py].

The recipes.cfg contains a field `recipes_path` (aka `$recipes_path` for this
doc) which is a path inside the repo of where the following can exist:
  * A `recipes` folder - contains entrypoint scripts (recipes) for the repo.
  * A `recipe_modules` folder - contains modules which may be depended on (used
    by) both recipe scripts as well as other modules (in this repo and any other
    repos which depend on it).

Additionally, `recipes.cfg` describes dependent repos with a git URL, commit
and fetch ref.


### Repo loading

When a dev runs `recipes.py` in their repo (their repo's copy of [recipes.py]),
it will find and parse the repo's `recipes.cfg` file, and identify the version
of the `recipe_engine` repo that the repo currently depends on.

It will then bootstrap (with git) a clone of the recipe engine repo in the
repo's `$recipes_path/.recipe_deps/recipe_engine` folder, and will invoke
[main.py] in that clone with the `--package` argument pointing to the absolute
path of the repo's recipes.cfg file.

Once `main.py` is running, it parses the `-O` overrides and the `--package`
flags, and builds a [RecipeDeps] object which owns the whole
`$recipes_path/.recipe_deps` folder. Constructing this object includes syncing
(with git) all dependencies described in `recipes.cfg`. Every dependent repo
will be checked out at `$recipes_path/.recipe_deps/$dep_repo_name`.

[RecipeDeps]: /recipe_engine/internal/recipe_deps.py

*** note
When dependencies are overridden on the command line with the `-O` flag, the
path specified for the dependency is used verbatim as the root of that
dependency repo; no git operations are performed.

This is the mechanism that the `recipes.py bundle` command employs to make
a hermetic recipe bundle; it generates a `recipes` script which passes `-O`
flags for ALL dependencies, causing the engine to run without doing any git
operations.
***

The `RecipeDeps` object also traverses (by scanning the checked-out state) all
the dependent repos to find their recipes and recipe_modules. It does not yet
read the code inside the files.

At this point, the chosen recipe subcommand's main function (e.g. [`run`],
[`test`], etc.) executes with the loaded `RecipeDeps` object, as well as any
other command-line flags the subcommand has defined.

Some commands just work on the structure of the `RecipeDeps` object, but most
will need to actually parse the recipe code from disk (e.g. to run it in one
form or another).

[run]: /recipe_engine/run.py
[test]: /recipe_engine/test.py


### Recipe Module loading

Modules are loaded by calling the `RecipeModule.do_import()` function. This is
equivalent in all ways to doing:

    from RECIPE_MODULES.repo_name import module_name

For example:

    from RECIPE_MODULES.depot_tools import gclient

This import magic is accomplished by installing a [PEP302] 'import hook' on
`sys.meta_path`. The hook is implemented in [recipe_module_importer.py]. Though
this sounds scary, it's actually the least-scary way to implement the recipe
module loading system, since it meshes with the way that python imports are
actually meant to be extended. You can read [PEP302] for details on how these
hooks are meant to work, but the TL;DR is that they are an object with two
methods, `find_module` and `load_module`. The first function is responsible for
saying "Yes! I know how to import the module you're requesting", or "No, I have
no idea what that is". The second function is responsible for actually loading
the code for the module and returning the module object.

Our importer behaves specially:
  * `RECIPE_MODULES` - Returns an empty module marked as a 'package' (i.e.,
    a module with submodules).
  * `RECIPE_MODULES.repo_name` - Verifies that the given project actually
    exists in `RecipeDeps`, then returns an empty module marked as a 'package'.
  * `RECIPE_MODULES.repo_name.module_name` - Verifies that the given module
    exists in this project, then uses `imp.find_module` and `imp.load_module` to
    actually do the loading. These are the bog-standard implementations for
    loading regular python modules. Additionally, we run a `patchup` function on
    this module before returning it.
  * `RECIPE_MODULES.repo_name.module_name....` - All submodules are imported
    without any alteration using `imp.find_module` and `imp.load_module`.

The "patchup" we do to the recipe module adds a few extra attributes to the
loaded module:
  * `NAME` - The short name of the module, e.g. "buildbucket".
  * `MODULE_DIRECTORY` - A recipe `Path` object used by the `api.resource()`
    function present on RecipeApi subclasses indirectly (see next item). AFAIK,
    nothing actually uses this directly, but "it seems like a good idea".
    * TODO(iannucci): Remove this and just use `module.__file__` instead.
  * `RESOURCE_DIRECTORY` - A recipe `Path` object used by the `api.resource()`
    function present on RecipeApi subclasses.
    * TODO(iannucci): Remove this and just use `module.__file__` instead.
  * `REPO_ROOT` - The Path to the root of the repo for this module, used by the
    `api.repo_resource()` method.
  * `CONFIG_CTX` - The `ConfigContext` instance defined in the module's
    config.py file (if any).
  * `DEPS` - The DEPS list/dictionary defined in the module's `__init__.py` file
    (if any). This is populated with () if `__init__.py` doesn't define it.
  * `API` - The `RecipeApiPlain` subclass found in the api.py file.
  * `TEST_API` - The `RecipeTestApi` subclass found in the test_api.py file (if
    any).
  * `PROPERTIES` - This finds the `PROPERTIES` dict in `__init__.py` and
    preprocesses it to 'bind' the property objects with the module name. These
    bound property objects will be used later when the recipe module is
    instantiated.

These patchup features are probably actually bugs/relics of the way that the
module loading system used to work; it would be good to minimize/remove these
over time.


### Recipe loading

Recipe loading is substantially simpler than loading modules. The recipe `.py`
file is exec'd with `execfile`, and then it's PROPERTIES dict (if any) is bound
the same way as it is for Recipe Modules.

Recipes also have a `RETURN_SCHEMA` object which defines the type of data that
this recipe returns. This is about 30% of a good idea, and hopefully I can
replace it with protobufs before anyone reads this paragraph :).


### Instantiating '**api**' objects

Now that we know how to load the __code__ for modules and recipes, we need to
actually instantiate them. This process starts at the recipe's `DEPS`
description, and walks down the entire DEPS tree, instantiating recipe modules
on the way back up (so, they're instantiated in topological order from bottom to
top of the dependency tree).

Instantiation can either be done in 'API' mode or 'TEST_API' mode. 'API' mode is
to generate the `api` object which is passed to `RunSteps`. 'TEST_API' mode is
to generate the `api` object which is passed to `GenTests`. Both modes traverse
the depedency graph the same way, but 'API' mode does a superset of the work
(since all `RecipeApi` objects have a reference to their `test_api` as
`self.test_api`).

Both `RecipeTestApi` and `RecipeApiPlain` classes have an `m` member injected
into them after construction, which contains all of the DEPS'd-in modules as
members.  So if a DEPS entry looks like:

    DEPS = [
      "some_repo_name/module",
      "other_module",
    ]

Then the `api` and `test_api` instances will have an 'm' member which contains
`module` and `other_module` as members, each of which is an instance of their
respective instantiated `api` class.

As the loader walks up the tree, each recipe module's `RecipeTestApi` (if any)
subclass is instantiated by calling its `__init__` and then injecting it's `m`
object.

If the loader is in 'API' mode, then the module's RecipeApiPlan subclass is also
instantiated, using the declared PROPERTIES as arguments to __init__, along with
`test_data`, which may be provided if the `api` is being used from the
`recipes.py test` subcommand to provide mock data for the execution of the test.
The `m` object is injected, and then any `_UnresolvedRequirement` objects are
injected as well.  Finally, after `m` has been injected and all
`_UnresolvedRequirement` objects are injected, the loader calls the instance's
`initialize()` method to allow it to do post-dependency initialization.

*** note
The `_UnresolvedRequirement` objects are currently only used to provide limited
'pinhole' interfaces into the recipe engine, such as the ability to run
a subprocess (step), or get access to the global properties that the recipe was
started with, etc. Typically these are only used by a single module somewhere in
the `recipe_engine` repo; user recipe modules are not expected to use these.
***


[recipes_cfg.proto]: /recipe_engine/recipes_cfg.proto
[main.py]: /recipe_engine/main.py
[recipes.py]: /recipes.py
[simple_cfg.py]: /recipe_engine/internal/simple_cfg.py
[recipe_module_importer.py]: /recipe_engine/internal/recipe_module_importer.py
[PEP302]: https://www.python.org/dev/peps/pep-0302/
