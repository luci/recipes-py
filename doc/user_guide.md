# Recipes

Recipes are a Python framework for writing Continuous Integration scripts (i.e.
what you might otherwise write as a bash script). Unlike bash scripts, they
are meant to:
  * Be testable
  * Be cross-platform
  * Allow code-sharing
  * Be locally runnable
  * Integrate with the LUCI UI (i.e. https://ci.chromium.org) to display
    subprocesses as "steps", and other UI attributes (step color, descriptive
    text, debugging logs, etc.)

*** note
For a more detailed guide to writing recipes, see the [recipe walkthrough](./walkthrough.md).
***

*** note
For more implementation details, please see [implementation_details].
***

[walkthrough]: ./walkthrough.md
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

Recipes were the evolution of these bash scripts; they are written in Python,
allow code sharing across repos, have a testing mechanism, etc. Arguably,
recipes have *too many* features at present, but we're hard at work removing
them where we can, to keep them simple :-)

## Introduction

This user guide will attempt to bootstrap your understanding of the recipes
ecosystem. This includes the setup of a recipe repo, user of the recipes.py
script, and the development flow for writing and testing recipes and recipe
modules.

## Runtime dependencies

Recipes depend on a few tools to be in the environment:

  * python: Currently recipes rely on Python 2.7.
  * `vpython`: This is a LUCI tool to manage python VirtualEnvs. Recipes rely
    on this for the recipe engine runtime dependencies (like the python
    protobuf libraries, etc.)
  * `cipd`: This is a LUCI tool to manage binary package distribution.

Additionally, most existing recipes depend on the following:

  * `luci-auth` - This is a LUCI tool to manage OAuth tokens; on bots it
    can mint tokens for service accounts installed as part of the Swarming task,
    and on dev machines it can mint tokens based on locally stored credentials
    (i.e. run `luci-auth login` to locally store credentials).

## Recipe repo setup

A recipe repo has a few essential requirements:
  * It is a git repo.
  * It contains a file called `//infra/config/recipes.cfg`. For historical
    reasons, this is a non-configurable path.
  * It contains the `recipes`, `recipe_modules`, and/or `recipe_proto` folders
    (in the `recipes_path` folder indicated by `recipes.cfg`. By default they
    are located at the base of the repository).
  * It contains a copy of [recipes.py] in its `recipes_path` folder.

[recipes.py]: /recipes.py

### The config file recipes.cfg

The `recipes.cfg` file is a JSONPB file, which is defined by the
[recipes_cfg.proto] protobuf file.

Its purpose is to tell the recipe engine about this repo, and indicate any
other repos that this repo depends on (including precise dependency pins). All
recipe repos will need to depend on the 'recipe_engine' repo (the repo
containing this user guide).

As part of this config, the repo needs an `id`, which should match the
LUCI-config project id for the repo; this `id` will show up when other recipe
repos depend on your repo.

Example [recipes.cfg](https://chromium.googlesource.com/chromium/tools/build/+/HEAD/infra/config/recipes.cfg).

[recipes_cfg.proto]: /recipe_engine/recipes_cfg.proto

### The recipes folder

The recipes folder contains a collection of python files and subfolders
containing python files, as well as subfolders containing JSON 'expectation'
files. Recipes are named by their file path (minus the `.py` extension).

A recipe in a subfolder includes that subfolder in its name; so
`/path/to/recipes/subdir/recipe.py` would have the name "subdir/recipe".

Example [recipes folder](https://chromium.googlesource.com/chromium/tools/build/+/HEAD/recipes/recipes).

### The recipe_modules folder

The `recipe_modules` folder contains subfolders, one per module. Unlike recipes,
the module namespace is flat in each repo. A recipe module directory contains
these files:

  * `__init__.py`: Contains the `DEPS`, `PROPERTIES`, etc. declarations for the
    recipe_module.
  * `api.py`: Contains the implementation of the recipe module.
  * `test_api.py`: Contains the implementation of the recipe module's fakes.

Example [recipe_modules folder](https://chromium.googlesource.com/chromium/tools/build/+/HEAD/recipes/recipe_modules).

### The recipe_proto folder

See [Working with Protobuf files](#Working-with-Protobuf-files) for details on
this folder and its contents.

## The recipes.py script

The `recipes.py` script is the entry point to the recipe_engine and to running
your recipe. Its primary functionality is to clone a copy of the recipe_engine
repo (matching the version in your `recipes.cfg` file), and then invoke the
main recipe_engine code with whatever command line you gave it.

This script invokes the recipe engine with `vpython`, which picks up a python
VirtualEnv suitable for the recipe engine (it includes things like
py-cryptography and the protobuf library).

There are a couple of important subcommands that you'll use frequently:
  * `run`: This command actually executes a single recipe.
  * `test`: This command runs the simulation tests and trains the generated
    README.recipes.md file as well as simulation expectation files. This also
    has a 'debug' option which is pretty helpful.

Less often-used:
  * `autoroll`: Automatically updates your `recipes.cfg` file with newer
    versions of the dependencies there. This rolls the recipes.cfg version.
    and also runs simulation tests to try to detect the largest 'trivial' roll,
    or the smallest 'non-trivial' roll.
  * `manual_roll`: Updates your `recipes.cfg` file with the smallest valid roll
    possible, but doesn't do any automated testing. It's useful for when you
    need to manually roll recipes (i.e. the automated roll doesn't find a
    valid trivial or non-trivial roll, due to API changes, etc.).
  * `bundle`: Extracts all files necessary to run the recipe without making any
    network requests (i.e. no git repository operations).

And very infrequently used:
  * `doc`: Shows/generates documentation for the recipes and modules from their
    python docstrings. However the `test train` subcommand will generate
    Markdown automatically from the docstrings, so you don't usually need to
    invoke this subcommand explicitly.
  * `fetch`: Explicitly runs the 'fetch' phase of the recipe engine (to sync
    all local git repos to the versions in `recipes.cfg`). However, this happens
    implicitly for all subcommands, and the `bundle` command is a superior way
    to prepare recipes for offline use.
  * `lint`: Runs some very simple static analysis on the recipes. This command
    is mostly invoked automatically from PRESUBMIT scripts so you don't need to
    run it manually.

It also has a couple tools for analyzing the recipe dependency graph:
  * `analyze`: Answers questions about the recipe dependency graph (for use in
    continuous integration scenarios).

### Overriding dependencies

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

### The run command

TODO(iannucci) - Document

### The test command

TODO(iannucci) - Document

### The autoroll command

TODO(iannucci) - Document

### The manual_roll command

Updates your repo's `recipes.cfg` file with the smallest valid roll possible.
This means that for all dependencies your repo has, the smallest number of
commits change between the previous value of recipes.cfg and the new value of
recipes.cfg.

This will print out the effective changelog to stdout as well, for help in
preparing a manual roll CL.

You can run this command repeatedly to find successive roll candidates.

### The bundle command

TODO(iannucci) - Document

## Writing recipes

A "recipe" is a Python script which the recipe engine can run and test. This
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

For a more detailed guide to writing recipes and recipe modules, see the
[walkthrough](./walkthrough.md)

### RunSteps

The `RunSteps` function has a signature like:

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

The `RunSteps` function may invoke any recipe module it wants via `api` (at its
most basic, a recipe would run steps via `api.step(...)` after including
'recipe_engine/step' in `DEPS`).

Additionally, the `RunSteps` function can return a summary and status of the build.
This is done by returning a `RawResult` object, which can be done like this:

    # Import proto that has RawResult object
    from PB.recipe_engine.result import RawResult
    # Import proto that has Status object
    from PB.go.chromium.org.luci.buildbucket.proto import common

    def RunSteps(api):
      # Run some recipe step
      try:
        api.step('do example', ...)
        return RawResult(
          status=common.SUCCESS,
          summary_markdown='Ran the example!',
        )
      except api.step.StepFailure:
        # The example will output json in the form of `{"error": string}`
        step_json = api.step.active_result.json.output
        return RawResult(
          status=common.FAILURE,
          summary_markdown=step_json['error'],
        )

*** note
Currently (as of 2019/06/24) the Recipe Engine still uses the `@@@annotation@@@` protocol
which prevents the `summary_markdown` field from propagating on `SUCCESS` statuses. So,
you can set `summary_markdown` in all cases from the recipe, but it will only be visible
on the build in conjunction with non-SUCCESS status value.
***

### GenTests

The `GenTests` function is a generator which yields test cases. Every test case:
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

### DEPS

The DEPS section of the recipe specifies what recipe modules this recipe depends
on. The DEPS section has two possible forms, a list and a dict.

As a list, DEPS can specify a module by its fully qualified name, like
`recipe_engine/step`, or its unqualified name (for modules in the same recipe
repo as the recipe) like `step`. The 'local name' of an entry is the last token
of the fully qualified name, or the whole name for an unqualified name (in this
example, the local name for both of these is just 'step').

As a dict, DEPS maps from a local name of your choosing to either the fully
qualified or unqualified name of the module. This would allow you to
disambiguate between modules which would end up having the same local name. For
example `{'my_archive': 'archive', 'archive': 'recipe_engine/archive'}`.

The recipe engine, when running your recipe, will inject an instance of each
DEPS'd recipe module into the `api` object passed to `RunSteps`. The instance
will be injected with the local name of the dependency. Within a given execution
of a recipe module instances behave like singletons; if a recipe and a module
both DEPS in the same other module (say 'tertiary'), there will only be one
instance of the 'tertiary' module.

### PROPERTIES and ENV_PROPERTIES

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

The properties can be set during testing by using the `properties` dependency.
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

## Writing recipe_modules

TODO(iannucci) - Document

See the relevant section in the [walkthrough](./walkthrough.md).

### PROPERTIES, GLOBAL_PROPERTIES and ENV_PROPERTIES

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

### Accessing recipe_modules as python modules

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

### Extending config.py

If you need to extend the configurations provided by another recipe module,
write your extensions in a file ending with `_config.py` in your recipe module
and then import that other module's "CONFIG_CTX" to add additional named
configurations to it (yes, this has very messy implications).

You can import the upstream module's CONFIG_CTX by using the recipe module
import syntax. For example, importing from the 'gclient' module in 'depot_tools'
looks like:

    from RECIPE_MODULES.depot_tools.gclient import CONFIG_CTX

## How recipes execute

TODO(iannucci) - Document

For more details, see [implementation_details.md](./implementation_details.md).

### Engine Properties

[engine_properties.proto] defines a list of properties that dynamically adjust the behavior of recipe engine. These properties are associated with key `$recipe_engine` in the input properties.

[engine_properties.proto]: /recipe_engine/engine_properties.proto

## How recipe simulation tests work

TODO(iannucci) - Document

### Protobufs in tests

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
              # The dollar sign is a literal character and must be included.
              '$my_repo/cool_module': CoolProps(...),
            }
        )
      )

## Recipe and module 'resources'

Recipes and Recipe modules can both have "resources" which are arbitrary
files that will be bundled with your recipe and available to use when the
recipe runs. These are most typically used to include additional python scripts
which will be invoked as steps during the execution of your recipe or module.

A given recipe "X" can store resource files in the adjacent folder
"X.resources". Similarly, a recipe module "M" can have a subdirectory "resources".

To get the Path to files within this folder, use `api.resource("filename")`. This
method supports multiple path segments as well, so something like
`api.resource("subdir", "filename")` works as well.

As an example, you might run a python script like:

```
# If this is the recipe file "//recipes/hello.py" then this would run
# "//recipes/hello.resources/my_script.py", and with the vpython spec
# "//recipes/hello.resources/.vpython3".
api.step("run my_script", ["vpython3", "-u", api.resource("my_script.py")])
```

These resources should be considered *implementation details* of your recipe or
module. It's not recommended to allow outside programs to use these resources
except via your recipe or module interface.


## Structured data passing for steps

TODO(iannucci) - Document

## Build UI manipulation

TODO(iannucci) - Document

## Testing recipes and recipe_modules

TODO(iannucci) - Document

## Issuing warnings in recipe modules

While recipe modules provide a way to share code across different repos (via
`DEPS`), it also means that changing the behavior of a recipe module may
potentially break recipes or recipe modules in downstream repos which depend on
it. Figuring out all such recipes or recipe modules requires substantial effort.

Recipes have a "warnings" feature that allows recipe authors to better alert
downstream consumers about upcoming breaking changes in a recipe module. The
recipe engine will issue notifications for all warnings hit during the
execution of simulation tests (i.e. `recipes.py test run` or `recipes.py test
train`). The engine groups the notifications by warning names.

### Defining a warning

A warning is defined in the file `recipe.warnings` under the recipe folder in a
repo. `recipes.warnings` is a text proto formatted file of
`DefinitionCollection` Message in [warning.proto]. Example as follows:

    monorail_bug_default {
      host: "bugs.chromium.org"
      project: "chromium"
    }
    warning {
      name: "MYMODULE_SWIZZLE_BADARG_USAGE"
      description: "The `badarg` argument on mymodule.swizzle is deprecated and replaced with swizmod."
      deadline: "2020-01-01"
      monorail_bug {
        id: 123456
      }
    }
    warning {
      name: "MYMODULE_DEPRECATION"
      # You can also write multiple line description
      description: "Deprecating MyModule in recipe_engine."
      description: "Use the equivalent MyModule in infra repo instead."
      description: "" # blank line
      description: "MyModule contains infra specific logic."
      deadline: "2020-12-31"
      monorail_bug {
        id: 987654
      }
      monorail_bug {
        project: "chrome-operations"
        id: 654321
      }
    }

The name of the warning must be unique within the `recipes.warnings` file. The
recipe engine will take the warning name and generate a fully-qualified warning
name of "$repo_name/$warning_name". This implies that multiple repos could
define warnings with the same repo-local name, since the engine will always
qualify them by the repo names (which already must be globally unique).

[warning.proto]: /recipe_engine/warning.proto

### Issuing a warning

A warning can be either issued in the recipe module code or for an entire
recipe module.

To issue warnings in your module code, declare a dependency to
`recipe_engine/warning` module via your module's `DEPS` first and then call the
`issue` method at the location where you want the warning to be issued. E.g.

```python
class MyModuleAPI(RecipeApi):
  def swizzle(self, arg1, arg2, badarg=None):
    if badarg is not None:
      self.m.warning.issue('MYMODULE_SWIZZLE_BADARG_USAGE')
      # the code will continue executing
      # ...
```

To issue warnings for the entire recipe module, set a `WARNINGS` variable in the
`__init__.py` of the targeted recipe module. E.g.

```python
# ${PATH_TO_RECIPE_FOLDER}/recipe_modules/my_module/__init__.py
DEPS = [
  # DEPS declaration
]

WARNINGS = [
  'MYMODULE_DEPRECATION'
]
```

### Running a simulation test for warnings

If the recipe code within a repo hits any issued warnings, the test summary
will contain output like:

    **********************************************************************
              WARNING: depot_tools/MYMODULE_SWIZZLE_BADARG_USAGE
                    Found 5 call sites and 0 import sites
    **********************************************************************
    Description:
      The `badarg` argument on mymodule.swizzle is deprecated and replaced with swizmod
    Deadline: 2020-01-01

    Bug Link: https://bugs.chromium.org/p/chromium/issues/detail?id=123456
    Call Sites:
      /path/to/recipe/folder/recipes/A.py:123 (and 234, 456)
      /path/to/recipe/folder/recipe_modules/B/api.py:567 (and 789)

    **********************************************************************
                 WARNING: recipe_engine/MYMODULE_DEPRECATION
                    Found 0 call sites and 2 import sites
    **********************************************************************
    Description:
      Deprecating MyModule in recipe_engine.
      Use the equivalent MyModule in infra repo instead.

      MyModule contains infra specific logic.
    Deadline: 2020-12-31

    Bug Links:
      https://bugs.chromium.org/p/chromium/issues/detail?id=987654
      https://bugs.chromium.org/p/chrome-operations/issues/detail?id=654321
    Import Sites:
      /path/to/recipe/folder/recipes/C.py
      /path/to/recipe/folder/recipe_modules/D/__init__.py

All issued warnings will be grouped by their fully qualified names. All
information in the definition will be displayed to provide more context about
each warning followed by `Call Sites` or `Import Sites` (could possibly have
both). Only `Call Sites` or `Import Sites` from the repo where simulation test
runs will be shown.

**Call Sites**: If a warning is issued in a function or method body of a recipe
module during a test run, Call Sites is all the unique locations where that
function/method are called. In other word, the direct outer frame of the frame
where warning is issued.

**Import Sites**: If a warning is issued for the entire recipe module via the
`WARNING` variable, Import Sites is the list of recipes and recipe modules which
have declared a dependency on that module.

### Advanced features of warnings

#### Escaping warnings

The recipe engine also provides a way to exclude code in a function from being
attributed to the call site for certain warnings. This is achieved by applying
the `@recipe_api.escape_warnings(*warning_regexps)` decorator to that function.
Each regex is matched against the fully-qualified name of the issued warning.

For example, the following code snippet attributes warning `FOO` from
`recipe_engine` repo or any warnings that ends with `BAR` emitted by
`method_contains_warning` to the CALLER of `cool_method`, instead of to
`cool_method` itself. Note that multiple frames in the call stack could be
escaped in this fashion, the recipe engine will walk the stack until it finds a
frame which is not escaped.

```python
from recipe_engine import recipe_api

class FooApi(recipe_api.RecipeApiPlain):

  @original_decorator
  # escape_warnings decorator needs to be the innermost decorator
  @recipe_api.escape_warnings('^recipe_engine/FOO$', '^.*BAR$')
  def cool_method(self):
    # warning will be issued in the following call
    self.m.bar.method_contains_warning()
    pass
```

There is also a shorthand decorator (`@recipe_api.escape_all_warnings`) which
escape the decorated function from all warnings.

#### CLI options for warnings

TODO(yiwzhang) - Document when CLI options are ready

## Detecting memory leaks with Pympler

To help detect memory leaks, recipe engine has a [property](#engine-properties)
named `memory_profiler.enable_snapshot`. It is false by default. If it is set
to true, the recipe engine will snapshot the memory before each step execution,
compare it with the snapshot of previous step and then print the diff to the
`$debug` log stream. This feature is backed by [Pympler] and the output in
debug log will look like as follows:

     types |   # objects |   total size
    ====== | =========== | ============
      list |        5399 |    553.40 KB
       str |        5398 |    323.04 KB
       int |         640 |     15.00 KB

[Pympler]: https://github.com/pympler/pympler

## Working with Protobuf files

The recipe engine facilitates the use of protobufs with builtin `protoc`
capabilities.

Due to the nature of `.proto` imports, the import lines in the generated python
code and the layout of recipes and modules (specifically, across multiple
repos), is a bit more involved than just putting the `.proto` files in a
directory, running `protoc` and calling it a day.

### Where Recipe Engine looks for .proto files

Recipe engine will look for proto files in 3 places in your recipe repo:
  * Mixed among the `recipe_modules` in your repo
  * Mixed among the recipes in your repo
  * In a `recipe_proto` directory (adjacent to your 'recipes' and/or
    `recipe_modules` directories)

For proto files which are only used in the recipe ecosystem, you should put
them either in `recipes/*` or `recipe_modules/*`. For proto files which
originate outside the recipe ecosystem (e.g. their source of truth is some
other repo), place them into the `recipe_proto` directory in an appropriate
subdirectory (so that `protoc` will find them where other protos expect to
import them).

### Protos in recipe modules

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

### Protos in the recipes folder

Your recipes may also define protos. It's required that the protos in the
recipe folder correspond 1:1 with an actual recipe. The name for this proto
file should be the recipe's name, but with '.proto' instead of '.py'. So, you
could have:

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

### The special case of recipe_engine protos

The recipe engine repo itself also has some protos defined within it's own
`recipe_engine` folder. These are the proto files [here](/recipe_engine).

The proto files are importable in other proto files as e.g.:

    import "recipe_engine/file.proto";

The generated protobuf libraries are importable as e.g.:

    import PB.recipe_engine.file

### The recipe_proto folder

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

### Using generated protos in your recipes and recipe modules

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

## Python3 Support

Status: Python3 support in recipes are still a work in progress as of Aug 2021.
But most commonly used commands (e.g. test, luciexe) are Python3 compatible. We
are working on making all engine-supplied recipe modules Python3 compatible.

### Indicating per-module/per-recipe compatibility

As part of this transition, recipes and recipe_modules may both indicate their
individual support for python2, python3 or both via the
`PYTHON_VERSION_COMPATIBILITY` variable, which should be set to one of:

  * "PY2"
  * "PY2+3"
  * "PY3"

For recipes this appears next to the `DEPS` declaration at the top of the
recipe, and for recipe_modules, this appears in the `__init__.py` file
along with any other statements (such as `DEPS`). If unspecified, it's
assumed that the related section of code is marked "PY2".

Example:

    # In /repo/recipe_modules/something/__init__.py
    PYTHON_VERSION_COMPATIBILITY = "PY2+3"  # compatible with py2 and py3

    # In /repo/recipes/a_recipe.py
    PYTHON_VERSION_COMPATIBILITY = "PY3"    # only compatible with py3

### Testing

The compatibility declaration will be used in `recipes.py test` to run the
tests under the appropriate Python interpreter(s) and then surface any errors
appropriately (i.e. Py3 errors from code claiming Py3 compatibility will be
marked as hard failures, otherwise they're suppressed warnings). Passing
additional `--py3-details` flag will show the details of suppressed warnings
in the test result.

If this recipe depends on modules (including transitive dependencies) with
irreconcilable `PYTHON_VERSION_COMPATIBILITY` declaration (e.g.
not-yet-migrated DEPS recipe module), any test failure for this recipe will
also become suppressed warnings meaning that the test command will succeed. The
test will become hard failure once all dependency modules of this recipes and
the recipe itself can reconcile on a Python version.

The reconciling logic is:

  * `PY2` + `PY2` = `PY2`
  * `PY2` + `PY2+3` = `PY2`
  * `PY3` + `PY3` = `PY3`
  * `PY3` + `PY2+3` = `PY3`
  * `PY2+3` + `PY2+3` = `PY2+3`

All other combinations will result in an irreconcilable Python version. Note
that you can use `recipes.py deps` command to print out all these (See
[Print Python 3 readiness info](#print-python-3-readiness-info) section for
detailed info).

Be aware that the compatibility declaration doesn't dictate the Python
interpreter used on that actual recipe run on a builder. So marking your
recipe as `PY3` will result in losing test coverage under Python 2
interpreter even though the actual build still runs recipe with Python 2.
If you intend to use Python 3 on your builder as well, please see
[Run recipe in Python 3 on a builder](#run-recipe-in-python-3-on-a-builder)
section.

*Known Issue*:

  * If the recipe is marked as `PY2+3` and the expectation file is expected to
    be changed, `recipes.py test train` may fail on the first pass with false
    negative result for Python 3 test because it is comparing with the previous
    expectation file instead of the one Python 2 test just generated. You can
    workaround it by simply running the train command again.
  * Sometimes, the "Insufficient coverage" error might be a false positive. It’s
    because of inconsistencies from 3rd-party Coverage library when combining
    results from different python interpreters. Possible situations:
      * Run `RECIPES_USE_PY3=true ./recipes.py test` for a recipe or module
        which isn’t yet marked as PY2+3 or PY3. The def line of a function with
        decorators might be reported as uncovered. You could:
          * Mark that recipe/module to PY2+3 or PY3, and solve any reported
            errors in running py3 tests.
          * OR: Add `# pragma: no cover` to the def line if you’re sure it’s
            covered.
      * Run `./recipes.py test`, for a recipe or module which is marked as PY3
        compatible. The line of `while True` or `if True` will be reported as
        uncovered. You could:
          * Assign `True` to a var and use that var in conditional statements.
          * OR: Mark `# pragma: no cover` to that line.

### Print Python 3 readiness info

The `recipes.py deps` command can be used to dump the Python 3 readiness
status of the supplied recipe or module and its dependencies. Each recipe or
module will show two statuses. The first one is based on its self-declared
`PYTHON_VERSION_COMPATIBILITY`. The second one is computed by walking through
its dependencies and checking their `PYTHON_VERSION_COMPATIBILITY` using
reconciling logic mentioned above.

### Run recipe in Python 3 on a builder

Recipe can run with Python 3 interpreter if [`luci.recipes.use_python3`
experiment] is enabled for this build. Note that it works only on builds
run with bbagent. Kitchen builds are being deprecated so please migrate your
builder.

This is achieved by BBAgent setting the envvar `$RECIPES_USE_PY3` to `true` and
the stubs generated with the `recipes.py bundle` subcommand will decide
the python version based on the envvar. The same envvar is also respected by
`recipes.py` so that you can run any recipe subcommand with Python3 interpreter
locally.

If you are launching a led build, you can enable the Python 3 experiment by
adding `led edit -experiment luci.recipes.use_python3=true` to your led
pipeline.

Note that, the `test` subcommand will always launch tests with both Python 2 and
Python 3 if necessary regardless the version of the Python interpreter that
executes the `test` subcommand. Therefore,
`RECIPES_USE_PY3=true recipes.py test` and
`RECIPES_USE_PY3=false recipes.py test` should yield the same result.

[`luci.recipes.use_python3` experiment]: https://source.chromium.org/chromium/infra/infra/+/main:go/src/go.chromium.org/luci/buildbucket/proto/project_config.proto;l=553-556;drc=1a075857890bfaa0c2084d41f29a843c4d762070

## Productionizing

TODO(iannucci) - Document

### Bundling

TODO(iannucci) - Document

### Rolling

TODO(iannucci) - Document

## Recipe Philosophy

TODO(iannucci) - Document

  * Recipes are glorified shell scripts
  * Recipes should be functions (small set of documented inputs and outputs).
  * Recipe inputs should have predictable effects on the behavior of the Recipe.

To document/discuss:
  * Structured data communication to/from steps
  * When to put something in a helper script or directly in the recipe

## Glossary

**recipe repo**: A git repository with an `infra/config/recipes.cfg` file.

**recipe**: An entry point into the recipes ecosystem, each recipe is a
  Python file with a `RunSteps` function.

**recipe_module**: A piece of shared code that multiple recipes can use.

**DEPS**: An list of the dependencies from a recipe to recipe modules,
  or from one recipe module to another.

**repo_name**: The name of a recipe repo, as indicated by the `repo_name`
  field in it's `recipes.cfg` file. This is used to qualify module dependencies
  from other repos.

**properties**: A JSON object that every recipe is started with; These are
  the input parameters to the recipe.

**output properties**: Similar to input properties but writeable. These
  properties are viewable in the LUCI UI and can be read by other systems
  that ingest LUCI builds.

**PROPERTIES**: An expression of a recipe or recipe module of the properties
  that it relies on.
