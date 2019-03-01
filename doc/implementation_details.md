# Recipe engine implementation details

This doc covers implementation details of the recipe engine and its processes.
Read this if you want to understand/modify how the recipes as a system work. For
general recipe developement, please see [user_guide.md](./user_guide.md).

[TOC]


## Recipe engine subcommands

All recipe engine subcommands live in the [commands] folder. The `__init__.py`
file here contains the entrypoint for all subcommand parsing `parse_and_run`
which is invoked from [main.py].

The commands module contains (as submodules) all of the subcommands that the
recipe engine supports. The protocol is pretty simple:

  * The subcommand lives in a submodule (either directory or .py file).
  * Each submodule has a `add_arguments(parser)` function (for directories, this
    is expected to be in the `__init__.py` file).
  * Each submodule may also define an optional `__cmd_priority__` field. This
    should be an integer which will be used to rank commands (e.g. so that 'run'
    and 'test' can preceed all other subcommands). Commands will be ordered
    first by __cmd_priority__ (lower values sort earlier) and then
    alphabetically. This is currently used to put `run` and `test` as the
    topmost arguments in the `recipes.py` help output.
  * The `add_arguments` function takes an argparse parser, and adds flags to it.
    The parser will be created:
    * using the module's name as the command name
    * using the module's `__doc__` to generate both the description and 'help'
      for the parser (help will be the first paragraph of `__doc__`).
  * In addition to adding flags, the function must also call:

      parser.set_defaults(
          postprocess_func=function(error, args), # optional
          func=function(args))                    # required

  * Where the 'args' parameter is the parsed CLI arguments and 'error' is the
    function to call if the preconditions for the subcommand aren't met.
  * postprocess_func should do any post-CLI checks and call `error(msg)` if the
    checks don't pass. Most subcommands don't need this, but it's a nice way to
    verify preconditions for the command.
  * func executes the actual subcommand.

The reason for this structure is so that the actual `func` can do lazy
importing; this is necessary if the subcommand requires protobufs to operate
correctly (which are only available after the CLI has successfully parsed).

All commands have `args.recipe_deps`, which is the resolved RecipeDeps instance
to use.

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


### Proto compilation

The recipe engine facilitates the use of protobufs with builtin `protoc`
capabilities. This is all implemented in [proto_support.py].

*** note
For the purposes of bundled recipes, it's possible to completely skip the proto
compilation step by using the --proto-override option to the engine. This is
exactly what `recipes.py bundle` generates so that builders don't need to do any
`protoc` activity on their startup.
***

Due to the nature of .proto imports, the generated python code (specifically
w.r.t. the generated `import` lines), and the layout of recipes and modules
(specifically, across multiple repos), is a bit more involved than just putting
the .proto files in a directory, running 'protoc' and calling it a day.

After loading all the repos, the engine gathers and compiles any `.proto` files
they contain into a single global namespace. The recipe engine looks for proto
files in 3 (well, 4) places in a repo:
  * Under the `recipe_modules` directory
    * Placed into the global namespace as `recipe_modules/$repo_name/*`.
  * Under the `recipes` directory
    * Placed into the global namespace as `recipes/$repo_name/*`.
  * Under the `recipe_engine` directory (only in the actual `recipe_engine`
    repo).
    * Placed into the global namespace as `recipe_engine/*`.
  * In a `recipe_proto` directory (adjacent to the 'recipes' and/or
    'recipe_modules' directories).
    * Placed directly into the global namespace.
    * May not contain anything in the `recipe_engine`, `recipes` or
      `recipe_modules` subdirectories.

While the engine gathers all the proto files, it sorts them and generates
a checksum of their contents. This is a SHA2 of the following:
  * `RECIPE_PB_VERSION` | `NUL` - The version of the recipe engine's compilation
    algorithm.
  * `PROTOC_VERSION` | `NUL` - The version of the protobuf library/compiler
    we're using.
  * `repo_name` | `NUL` | `NUL` - The name of the repo. Then, for every .proto
    in the repo we hash:
    * `relative_path_in_repo` | `NUL`
    * `relative_path_of_global_destination` | `NUL`
    * `githash_of_content` | `NUL`

The `githash_of_content` is defined by git's "blob" hashing scheme (but is
currently implemented in pure-python).

Once we've gathered all proto files and have computed the checksum, we verify
the checksum against `.recipe_deps/_pb/PB/csum`. If it's the same, we conclude
that the currently cached protos are the same as what we're about to compile.

If not, we copy all protos to a temporary directory reflecting their expected
structure (see remarks about "global namespace" above). This structure is
important to allow `protoc` to correctly resolve `import` lines in proto files,
as well as to make the correct python import lines in the generated code.

Once the proto files are in place, we compile them all with `protoc` into
another tempdir.

We then rewrite and rename all of the generated `_pb2` files to change their
import lines from:

    from path.to.package import blah_pb2 as <unique_id_in_file>

to:

    from PB.path.to.package import blah as <unique_id_in_file>

And rename them from `*_pb2` to `*`. We also generate empty `__init__.py` files.

After this, we write `csum`, and do a rename-swap of this tempdir to
`.recipe_deps/_pb/PB`. Finally, we put `.recipe_deps/_pb` onto `sys.path`.


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


[commands]: /recipe_engine/internal/commands
[main.py]: /recipe_engine/main.py
[PEP302]: https://www.python.org/dev/peps/pep-0302/
[proto_support.py]: /recipe_engine/internal/proto_support.py
[recipe_module_importer.py]: /recipe_engine/internal/recipe_module_importer.py
[recipes.py]: /recipes.py
[recipes_cfg.proto]: /recipe_engine/recipes_cfg.proto
[simple_cfg.py]: /recipe_engine/internal/simple_cfg.py
