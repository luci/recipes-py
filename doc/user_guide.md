# Recipes

Recipes are a python framework for writing Continuous Integration scripts (i.e.
what you might otherwise write as a bash script). Unlike bash scripts, they
are meant to:
  * Be testable
  * Be cross-platform
  * Allow code-sharing
  * Be locally runnable
  * Integrate with the LUCI UI (e.g. ci.chromium.org) to display
    subprocesses as "steps", and other UI attributes (step color,
    descriptive text, debugging logs, etc.)

*** note
This user guide is a work in progress, and is a revised version of the
[old_user_guide]. Once this guide is fully updated, the old version will
be removed.
***

[old_user_guide]: ./old_user_guide.md

*** note
For more implementation details, please see [implementation_details].
***

[implementation_details]: ./implementation_details.md


[TOC]

## Background

Chromium previously used BuildBot for its builds, which stored the definition of
a builder's actions as 'Build Factories' on the service side, requiring service
redeployment (including temporary outages) in order to make changes to them.
Additionally the build factories produced all steps-to-be-run at the beginning
of the build; there was no easy way to calculate a future step from the results
of running an intermediate step. This made it very difficult to iterate on the
builds.

We initially introduced a protocol to BuildBot to allow a script running in the
build to control the presentation of the build on BuildBot (i.e. telling the
service that new steps were running and their status, etc.). For a while
a couple sub-teams used bash scripts to execute their builds, manually emitting
the signalling protocol interspersed with stdout. This provided the ability
to de-couple working on what-the-build-does from the running BuildBot service,
allowing changes to the build without redeployment of the service.

Recipes were the evolution of these bash scripts; they are written in python,
allow code sharing across repos, have a testing mechanism, etc.

Arguably, recipes have *TOO MANY* features at present, but we're hard at work
removing them where we can, to keep them simple :).

## Intro

This README will attempt to bootstrap your understanding of the recipes
ecosystem. This includes:

  * Runtime dependencies
  * Initial repo setup
  * The `recipes.py` command
  * Writing recipes
  * Writing recipe_modules
  * Structured data passing for steps
  * Build UI manipulation
  * Testing recipes and recipe_modules
  * Productionizing a recipe repo
  * Recipe Philosophy

### Runtime dependencies

Recipes depend on a couple tools to be in the environment:

  * Python (2.7) - Currently recipes rely on python 2.7.
  * `vpython` - This is a LUCI tool to manage python VirtualEnvs. Recipes rely
    on this for the recipe engine runtime dependencies (like the python
    protobuf libraries, etc.)
  * `cipd` - This is a LUCI tool to manage binary package distribution.

Additionally, most existing recipes depend on the following:

  * `luci-auth` - This is a LUCI tool to manage OAuth tokens; on bots it
    can mint tokens for service accounts installed as part of the Swarming task,
    and on dev machines it can mint tokens based on locally stored credentials
    (i.e. run `luci-auth login` to locally store credentials).

### Initial repo setup

A recipe repo has a couple essential requirements:
  * It is a git repo
  * It contains a file called `//infra/config/recipes.cfg`. For historical
    reasons, this is a non-configurable path.
  * It contains 'recipes', 'recipe_modules', and/or 'recipe_proto' folders (in
    the `recipes_path` folder indicated by `recipes.cfg`. By default they are
    located at the base of the repository).
  * It contains a copy of [recipes.py] in its `recipes_path` folder.

[recipes.py]: /recipes.py

#### recipes.cfg

The `recipes.cfg` file is a JSONPB file, which is defined by the
[recipes_cfg.proto] protobuf file.

Its purpose is to tell the recipe engine about this repo, and indicate any
other repos that this repo depends on (including precise dependency pins). All
recipe repos will need to depend on the 'recipe_engine' repo (the repo
containing this user_guide).

As part of this config, the repo needs an `id`, which should match the
LUCI-config project id for the repo; this id will show up when other recipe
repos depend on your repo.

Example [recipes.cfg](https://chromium.googlesource.com/chromium/tools/build/+/master/infra/config/recipes.cfg).

[recipes_cfg.proto]: /recipe_engine/recipes_cfg.proto

#### Recipes folder

The recipes folder contains a collection of python files and subfolders
containing python files, as well as subfolders containing JSON 'expectation'
files. Recipes are named by their file path (minus the `.py` extension).

A recipe in a subfolder includes that subfolder in its name; so
`/path/to/recipes/subdir/recipe.py` would have the name "subdir/recipe".

Example [recipes folder](https://chromium.googlesource.com/chromium/tools/build/+/master/scripts/slave/recipes).

#### recipe_modules folder

The recipe_modules folder contains subfolders, one per module. Unlike recipes,
the module namespace is flat in each repo. A recipe_module is composed of
a couple files:

  * `__init__.py` - Contains the `DEPS`, `PROPERTIES`, etc. declarations for the
    recipe_module.
  * `api.py` - Contains the implementation of the recipe module.
  * `test_api.py` - Contains the implementation of the recipe module's fakes.

Example [recipe_modules folder](https://chromium.googlesource.com/chromium/tools/build/+/master/scripts/slave/recipe_modules).

#### recipe_proto folder

See `Working with Protobufs` for details on this folder and it's contents.

#### The `recipes.py` script

The `recipes.py` script is the entrypoint to the recipe_engine. Its primary
functionality is to clone a copy of the recipe_engine repo (matching the version
in your `recipes.cfg` file), and then invoke the main recipe_engine code with
whatever command line you gave it.

This script invokes the recipe engine with `vpython`, which picks up a python
VirtualEnv suitable for the recipe engine (it includes things like
py-cryptography and the protobuf library).

### The `recipes.py` command

The recipes.py command is the main entrypoint to your recipe. It has a couple
important subcommands that you'll use frequently:
  * `run` - This command actually executes a single recipe
  * `test` - This command runs the simulation tests and trains the generated
    README.recipes.md file as well as simulation expectation files. This also
    has a 'debug' option which is pretty helpful.

Less often-used:
  * `autoroll` - Automatically updates your `recipes.cfg` file with newer
    versions of the dependencies there. This rolls the recipes.cfg version
    and also runs simulation tests to try to detect the largest 'trivial' roll,
    or the smallest 'non-trivial' roll.
  * `manual_roll` - Updates your `recipes.cfg` file with the smallest valid roll
    possible, but doesn't do any automated testing. It's useful for when you
    need to manually roll recipes (i.e. the automated roll doesn't find a
    valid trivial or non-trivial roll, due to API changes, etc.)
  * `bundle` - Extracts all files necessary to run the recipe without making any
    network requests (i.e. no git repository operations).

And very infrequently used:
  * `doc` - Shows/generates documentation for the recipes and modules from their
    python docstrings. However the `test train` subcommand will generate
    Markdown automatically from the docstrings, so you don't usually need to
    invoke this subcommand explicitly.
  * `fetch` - Explicitly runs the 'fetch' phase of the recipe engine (to sync
    all local git repos to the versions in `recipes.cfg`). However, this happens
    implicitly for all subcommands, and the `bundle` command is a superior way
    to prepare recipes for offline use.
  * `lint` - Runs some very simple static analysis on the recipes. This command
    is mostly invoked automatically from PRESUBMIT scripts so you don't need to
    run it manually.

It also has a couple tools for analyzing the recipe dependency graph:
  * `analyze` - Answers questions about the recipe dependency graph (for use in
    continuous integration scenarios).

#### Overriding dependencies

If you're developing recipes locally, you may find the need to work on changes
in multiple recipe repos simultaneously. You can override a dependency for
a recipe repo with the `-O` option to `recipes.py`, for any of its subcommands.

For example, you may want to change the behavior of the upstream repo and
see how it affects the behavior of the recipes in the `dependent` repo (which
presumably depends on the upstream repo). To do this you would:

    $ # Hack on the upstream repo locally to make your change
    $ cd /path/to/dependent/repo
    $ ./recipes.py -O upstream_id=/path/to/upstream/repo test train
    <uses your local upstream repo, regardless of what recipe.cfg specifies>

This works for all dependency repos, and can be specified multiple times to
override more than one dependency.

#### The `run` command

TODO(iannucci) - Document

#### The `test` command

TODO(iannucci) - Document

#### The `autoroll` command

TODO(iannucci) - Document

#### The `manual_roll` command

Updates your repo's `recipes.cfg` file with the smallest valid roll possible.
This means that for all dependencies your repo has, the smallest number of
commits change between the previous value of recipes.cfg and the new value of
recipes.cfg.

This will print out the effective changelog to stdout as well, for help in
preparing a manual roll CL.

You can run this command repeatedly to find successive roll candidates.

#### The `bundle` command

TODO(iannucci) - Document

### Writing recipes

A "recipe" is a python script which the recipe engine can run and test. This
script:
  * Must have a RunSteps function
  * Must have a GenTests generator
  * May have a DEPS list
  * May have a `PROPERTIES` declaration
  * May have a `ENV_PROPERTIES` declaration

Recipes must exist in one of the following places in a recipe repo:
  * Under the `recipes` directory
  * Under a `recipe_modules/*/examples` directory
  * Under a `recipe_modules/*/tests` directory
  * Under a `recipe_modules/*/run` directory

Recipes in subfolders of these are also permitted. Recipes in the global recipe
directory have a name which is the path of the recipe script relative to the
recipe folder containing it. If the recipe is located under a recipe module
folder, the name is prepended with the module's name and a colon. For example:

    //recipes/something.py                      ->  "something"
    //recipes/sub/something.py                  ->  "sub/something"
    //recipe_modules/foo/tests/something.py     ->  "foo:tests/something"
    //recipe_modules/foo/run/sub/something.py   ->  "foo:run/sub/something"

Here's a simple example recipe:

    DEPS = [
      "recipe_engine/step",
    ]

    def RunSteps(api):
      # This runs a single step called "say hello" which executes the `echo`
      # program to print 'hello' to stdout. `echo` is assumed to be resolvable
      # via $PATH here.
      api.step('say hello', ['echo', 'hello'])

    def GenTests(api):
      # yields a single test case called 'basic' which has no particular inputs
      # and asserts that the step 'say hello' runs.
      yield (
          api.test('basic')
        + api.post_check(lambda check, steps: check('say hello' in steps))
      )

#### `RunSteps`

The RunSteps function has a signature like:

     # RunSteps(api[, properties][, env_properties])
     # For example:

     # Neither PROPERTIES or ENV_PROPERTIES are declared
     def RunSteps(api):

     # PROPERTIES(proto message)
     def RunSteps(api, properties):

     # PROPERTIES(proto message) and ENV_PROPERTIES(proto message)
     def RunSteps(api, properties, env_properties):

     # ENV_PROPERTIES(proto message)
     def RunSteps(api, env_properties):

     # (DEPRECATED) Old style PROPERTIES declaration.
     def RunSteps(api, name, of, properties):

Where `api` is a python object containing all loaded `DEPS` (see section on
`DEPS` below), and the properties arguments are loaded from the properties
passed in to the recipe when the recipe is started.

The RunSteps function may invoke any recipe module it wants via `api` (at its
most basic, a recipe would run steps via `api.step(...)` after including
'recipe_engine/step' in `DEPS`).

#### `GenTests`

The GenTests function is a generator which yields test cases. Every test case:
  * Has a unique name
  * Specifies input properties for the test
  * Specifies input data for recipe modules
    * e.g. 'paths which exist' for the `recipe_engine/path` module, what OS and
      architecture the `recipe_engine/platform` module should simulate, etc.
  * Specifies the behavior of various steps by name (i.e. their return code, the
    output from placeholders)
  * Assertions about steps which should have run (or should not have run) given
    those inputs.
  * Filters for the 'test expectation' of the test case to omit details from the
    test expectations which aren't relevant to the test case.

Each test case also produces a test expectation file adjacent to the recipe; the
final state of the recipe execution in the form of a listing of the steps that
have run. The test expectation files are written to a folder which is generated
by replacing the '.py' extension of the recipe script with '.expected/'.

#### `DEPS`

The DEPS section of the recipe specifies what recipe modules this recipe depends
on. The DEPS section has two possible forms, a list and a dict.

As a list, DEPS can specify a module by its fully qualified name, like
`recipe_engine/step`, or its unqualified name (for modules in the same recipe
repo as the recipe) like `step`. The 'local name' of an entry is the last token
of the fully qualified name, or the whole name for an unqualified name (in this
example, the local name for both of these is just 'step').

As a dict, DEPS maps from a local name of your choosing to either the fully
qualified or unqulaified name of the module. This would allow you to
disambiguate between modules which would end up having the same local name. For
example `{'my_archive': 'archive', 'archive': 'recipe_engine/archive'}`.

The recipe engine, when running your recipe, will inject an instance of each
DEPS'd recipe module into the `api` object passed to `RunSteps`. The instance
will be injected with the local name of the dependency. Within a given execution
of a recipe module instances behave like singletons; if a recipe and a module
both DEPS in the same other module (say 'tertiary'), there will only be one
instance of the 'tertiary' module.

#### `PROPERTIES` and `ENV_PROPERTIES`

Recipe code has a couple ways to observe the input properties. Currently the
best way is to define a proto message and then set this as the `PROPERTIES`
value in your recipe:

    # my_recipe.proto
    syntax = "proto3";
    package recipes.repo_name.my_recipe;
    message InputProperties {
      int32 an_int = 1;
      string some_string = 2;
      bool a_bool = 3;
    }

    message EnvProperties {
      int32 SOME_ENVVAR = 1;    // All envvar keys must be capitalized.
      string OTHER_ENVVAR = 2;
    }

Then import the new proto message in the recipe.

    # my_recipe.py
    from PB.recipes.repo_name.my_recipe import InputProperties
    from PB.recipes.repo_name.my_recipe import EnvProperties

    # Setting this here makes it available in the
    # parameters of RunSteps(...)
    PROPERTIES = InputProperties
    ENV_PROPERTIES = EnvProperties

    # More information on the RunStep signature can
    # be found in the RunSteps section above
    def RunSteps(api, properties, env_properties):
      # properties and env_properties are instances of their respective proto
      # messages.
      # example use case
      if properties.a_bool:
        # do something
      elif properties.some_string == 'something important':
        if env_properties.SOME_ENVVAR == 0:
          # do something else
      ...

The properties can be set during testing by using the `properties` dependancy.
This enables the ability to test different parts of the run step in the recipe.

    # my_recipe.py
    from PB.recipes.repo_name.my_recipe import InputProperties
    from PB.recipes.repo_name.my_recipe import EnvProperties

    DEPS = [
      'recipe_engine/properties'
    ]

    PROPERTIES = InputProperties
    ENV_PROPERTIES = EnvProperties

    def RunSteps(api, properties, env_properties):
      # properties and env_properties are instances of their respective proto
      # messages.
      # example use case
      if properties.a_bool:
        # do something
      elif properties.some_string == 'something important':
        if env_properties.SOME_ENVVAR == 0:
          # do something else
      ...

    # This tests the above code
    def GenTests(api):
      yield (
        api.test('properties example') +
        api.properties(
          InputProperties(
            an_int=-1,
            some_string='something important',
            a_bool=False
          )
        ) +
        api.properties.environ(
          EnvProperties(SOME_ENVVAR=0)
        )
      )

In a recipe, `PROPERTIES` is populated by taking the input property JSON object
for the recipe engine, removing all keys beginning with '$' and then decoding
the remaining object as JSONPB into the `PROPERTIES` message. Keys beginning
with '$' are reserved by the recipe engine and/or recipe modules.

The `ENV_PROPERTIES` is populated by taking the current environment variables
(i.e. `os.environ`), capitalizing all keys (i.e. `key.upper()`) then decoding
that into the `ENV_PROPERTIES` message.

The other way to access properties (which will eventually be deprecated) is
directly via the `recipe_engine/properties` module. This method is very loose
compared to direct PROPERTIES declarations and can lead to difficult to debug
recipe code (i.e. different recipes using the same property for different
things, or dozens of seemingly unrelated places all interpreting the same
property, different default values, etc.). Additionally, `api.properties` does
not allow access to environment variables.

There's another way to define `PROPERTIES` which is deprecated, but it has no
advantages over the proto method, and will (hopefully) be deleted soon.

### Writing recipe_modules

TODO(iannucci) - Document

#### `PROPERTIES`, `GLOBAL_PROPERTIES` and `ENV_PROPERTIES`

In a recipe module's `__init__.py`, you may specify `PROPERTIES` and
`ENV_PROPERTIES` the same way that you do for a recipe, with the exception that
a recipe module's `PROPERTIES` object will be decoded from the input property of
the form `"$recipe_repo/module_name"`. This input property is expected to be
a JSON object, and will be decoded as JSONPB into the `PROPERTIES` message of
the recipe module.

For legacy reasons, some recipe modules are actually configured by top-level
(non-namespaced) properties. To support this, recipe modules may also specify
a `GLOBAL_PROPERTIES` message which is decoded in the same way a recipe's
`PROPERTIES` message is decoded (i.e. all the input properties sans properties
beginning with '$').

Example:

    # recipe_modules/something/my_proto.proto
    syntax = "proto3";
    package recipe_modules.repo_name.something;
    message InputProperties {
      string some_string = 1;
    }
    message GlobalProperties {
      string global_string = 1;
    }
    message EnvProperties {
      string ENV_STRING = 1;  // All envvar keys must be capitalized.
    }

    # __init__.py
    from PB.recipe_modules.repo_name.something import my_proto

    PROPERTIES = my_proto.InputProperties

    # Note: if you're writing NEW module code that uses global properties, you
    # should strongly consider NOT doing that. Please talk to your local recipe
    # expert if you're unsure.
    GLOBAL_PROPERTIES = my_proto.GlobalProperties
    ENV_PROPERTIES = my_proto.EnvProperties

    # api.py
    from recipe_engine.recipe_api import RecipeApi

    class MyApi(RecipeApi):
      def __init__(self, props, globals, envvars, **kwargs):
        super(MyApi, self).__init__(**kwargs)

        self.prop = props.some_string
        self.global_prop = globals.global_string
        self.env_prop = envvars.ENV_STRING

In this example, you could set `prop` and `global_prop` with the following
property JSON:

    {
      "global_string": "value for global_prop",
      "$repo_name/something": {
        "some_string": "value for prop",
      },
    }

And `env_prop` could be set by setting the environment variable `$ENV_STRING`.

#### Accessing recipe_modules as python modules

While recipe modules provide a way to share 'recipe' code (via `DEPS`), they are
also regular python modules, and occasionally you may find yourself wishing to
directly `import` some code from a recipe module.

You may do this by importing the module from the special `RECIPE_MODULES`
namespace; This namespace contains all reachable modules (i.e. from repos
specified in your `recipes.cfg` file) sub namespaced by `repo_name` and
`module_name`. This looks like:

    from RECIPE_MODULES.repo_name.module_name import python_module
    from RECIPE_MODULES.repo_name.module_name.python_module import Object

etc. Everything past the `RECIPE_MODULES.repo_name.module_name` bit works
exactly like any regular python import statement.

### Writing recipe_module config.py

*** note
The config subsystem of recipes is very messy and we do not recommend adding
additional dependencies on it. However some important modules (like `gclient` in
depot_tools) still use it, and so this documentation section exists.

We're looking to introduce native protobuf support as a means of fully
deprecating and eventually removing config.py, so this section is very sparse
without a "TODO" to document it more. I'll be adding additional documentation
for it as strictly necessary.
***

#### Extending config.py

If you need to extend the configurations provided by another recipe module,
write your extensions in a file ending with `_config.py` in your recipe module
and then import that other module's "CONFIG_CTX" to add additional named
configurations to it (yes, this has very messy implications).

You can import the upstream module's CONFIG_CTX by using the recipe module
import syntax. For example, importing from the 'gclient' module in 'depot_tools'
looks like:

    from RECIPE_MODULES.depot_tools.gclient import CONFIG_CTX

### How recipes execute

TODO(iannucci) - Document

### How recipe simulation tests work

TODO(iannucci) - Document

#### Protobufs in tests

Because `PROPERTIES` (and friends) may be defined in terms of protobufs, you may
also pass proto messages in your tests when using the `properties` recipe
module.

For example:

    # global properties used by this recipe
    from PB.recipes.my_repo.my_recipe import InputProps

    # global properties used by e.g. 'bot_update'
    from PB.recipe_modules.depot_tools.bot_update.protos import GlobalProps

    # module-specific properties used by 'cool_module'
    from PB.recipe_modules.my_repo.cool_module.protos import CoolProps

    DEPS = [
      "recipe_engine/properties",
      "some_repo/cool_module",
    ]

    PROPERTIES = InputProps

    def RunSteps(api, props):
       ...

    def GenTests(api):
      yield (
          api.test('basic')
        + api.properties(
            InputProps(...),
            GlobalProps(...),
            **{
              '$my_repo/cool_module': CoolProps(...),
            }
        )
      )

### Structured data passing for steps

TODO(iannucci) - Document

### Build UI manipulation

TODO(iannucci) - Document

### Testing recipes and recipe_modules

TODO(iannucci) - Document

### Working with Protobufs.

The recipe engine facilitates the use of protobufs with builtin `protoc`
capabilities.

Due to the nature of .proto imports, the generated python code (specifically
w.r.t. the generated `import` lines), and the layout of recipes and modules
(specifically, across multiple repos), is a bit more involved than just putting
the .proto files in a directory, running 'protoc' and calling it a day.

#### Where Recipe Engine looks for .proto files

Recipe engine will look for proto files in 3 places in your recipe repo:
  * Mixed among the `recipe_modules` in your repo
  * Mixed among the recipes in your repo
  * In a `recipe_proto` directory (adjacent to your 'recipes' and/or
    `recipe_modules` directories)

For proto files which are only used in the recipe ecosystem, you should put them
either in `recipes/*` or `recipe_modules/*`. For proto files which originate
outside the recipe ecosystem (e.g. their source of truth is some other repo),
place them into the `recipe_proto` directory in an appropriate subdirectory (so
that `protoc` will find them where other protos expect to import them).

##### recipe_modules

Your recipe modules can have any .proto files they want, in any subdirectory
structure that they want (the subdirectories do not need to be python modules,
i.e. they are not required to have an `__init__.py` file). So you could have:

    recipe_modules/
      module_A/
        cool.proto
        other.proto
        subdir/
          sub.proto

*** note
The 'package' line in the protos MUST be in the form of:

    package "recipe_modules.repo_name.module_name.path.holding_file";

So if you had `.../recipe_modules/foo/path/holding_file/file.proto` in the
"build" repo, its package must be `recipe_modules.build.foo.path.holding_file`.
Note that this is the traditional way to namespace proto files in the same
directory, but that this differs from how the package line for `recipes` works
below.
***

The proto files are importable in other proto files as e.g.:

    import "recipe_modules/repo_name/module_name/path/to/file.proto";

The generated protobuf libraries are importable as e.g.:

    import PB.recipe_modules.repo_name.module_name.path.to.file

##### recipes folder

Your recipes may also define protos. It's required that the protos in the recipe
folder correspond 1:1 with an actual recipe. The name for this proto file should
be the recipe's name, but with '.proto' instead of '.py'. So, you could have:

    recipes/
      my_recipe.py
      my_recipe.proto
      subdir/
        sub_recipe.py
        sub_recipe.proto

If you need to have common messages which are shared between recipes, put them
under the `recipe_modules` directory.

*** note
The 'package' line in the proto MUST be in the form of:

    package "recipes.repo_name.path.to.file";

So if you had a proto named `.../recipes/path/to/file.proto` in the "build"
repo, its package must be "recipes.build.path.to.file".

**Note that this includes the proto file name!**

This is done because otherwise all (unrelated) recipe protos in the same
directory would have to share a namespace, and we'd like to permit common
message names like `Input` and `Output` on a per-recipe basis instead of
`RecipeNameInput`, etc.
***

The proto files are importable in other proto files as e.g.:

    import "recipes/repo_name/path/to/file.proto";

The generated protobuf libraries are importable as e.g.:

    import PB.recipes.repo_name.path.to.file

##### **Special Case** recipe_engine protos

The recipe engine repo itself also has some protos defined within it's own
`recipe_engine` folder. These are the proto files [here](/recipe_engine).

The proto files are importable in other proto files as e.g.:

    import "recipe_engine/file.proto";

The generated protobuf libraries are importable as e.g.:

    import PB.recipe_engine.file

##### recipe_proto folder

The 'recipe_proto' directory can have arbitrary proto files in it from external
sources (i.e. from other repos), and organized using that project's folder
naming scheme. This is important to allow external proto files to work without
modification (due to `import` lines in proto files; if proto A imports
"go.chromium.org/luci/something/something.proto", then protoc needs to find
"something.proto" in the "go.chromium.org/luci/something" subdirectory).

Note that the following top-level folders are reserved under `recipe_proto`. All
of these directories are managed by the recipe engine (as documented above):
  * `recipe_engine`
  * `recipe_modules`
  * `recipes`

These are ALSO reserved proto package namespaces, i.e. it's invalid to have
a proto under a `recipe_proto` folder whose proto package line starts with
'recipes.'.

It's invalid for two recipe repos to both define protos under their
`recipe_proto` folders with the same path. This will cause proto compilation in
the downstream repo to fail. This usually just means that the downstream repo
needs to stop including those proto files, since it will be able to import them
from the upstream repo which now includes them.

#### Using generated protos in your `recipes` / `recipe_modules`

Once the protos are generated, you can import them anywhere in the recipe
ecosystem by doing:

    # from recipe_proto/external.example.com/repo_name/proto_name.proto
    from PB.external.example.com.repo_name import proto_name

    # from recipe_engine/proto_name.proto
    from PB.recipe_engine import proto_name

    # from repo_name.git//.../recipe_modules/module_name/proto_name.proto
    from PB.recipe_modules.repo_name.module_name import proto_name

    # from repo_name.git//.../recipes/recipe_name.proto
    from PB.recipes.repo_name import recipe_name

### Productionizing

TODO(iannucci) - Document

#### Bundling

TODO(iannucci) - Document

#### Rolling

TODO(iannucci) - Document

### Recipe Philosophy

TODO(iannucci) - Document

  * Recipes are glorified shell scripts
  * Recipes should be functions (small set of documented inputs and outputs).
  * Recipe inputs should have predictable effects on the behavior of the Recipe.
  * Structured data communication to/from steps
  * When to put something in a helper script or directly in the recipe

## Glossary

**recipe repo** -- A git repository with an 'infra/config/recipes.cfg' file.

**recipe** -- An entry point into the recipes ecosystem; a "main" function.

**recipe_module** -- A piece of shared code that multiple recipes can use.

**DEPS** -- An expression of the dependency from a recipe to a recipe_module,
  or from one recipe_module to another.

**repo_name** -- The name of a recipe repo, as indicated by the `repo_name`
  field in it's recipes.cfg file. This is used to qualify module dependencies
  from other repos.

**properties** -- A JSON object that every recipe is started with; These are
  the input parameters to the recipe.

**output properties** -- TODO(iannucci)

**PROPERTIES** -- An expression of a recipe or recipe_module of the properties
  that it relies on.
