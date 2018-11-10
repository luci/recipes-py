# Recipes

Recipes are a python framework for writing Continuous Intergration scripts (i.e.
what you might otherwise write as a bash script). Unlike bash scripts, they
are meant to:
  * Be testable
  * Be cross-platform
  * Allow code-sharing
  * Be locally runnable
  * Integrate with the LUCI UI (e.g. ci.chromium.org) to display
    subprocesses as "steps", and other UI attributes (step color,
    descriptive text, debugging logs, etc.)

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

Additionally, most existing recipes depend on the following:

  * `cipd` - This is a LUCI tool to manage binary package distribution.
  * `luci-auth` - This is a LUCI tool to manage OAuth tokens; on bots it
    can mint tokens for service accounts installed as part of the Swarming task,
    and on dev machines it can mint tokens based on locally stored credentials
    (i.e. run `luci-auth login` to locally store credentials).

### Initial repo setup

A recipe repo has a couple essential requirements:
  * It is a git repo
  * It contains a file called `//infra/config/recipes.cfg`. For historical
    reasons, this is a non-configurable path.
  * It contains 'recipes', 'recipe_modules' folders (in the `recipes_path`
    folder indicated by `recipes.cfg`. By default they are located at the base
    of the repository).
  * It contains a copy of [recipes.py] in its `recipes_path` folder.

[recipes.py]: /doc/recipes.py

#### recipes.cfg

The `recipes.cfg` file is a JSONPB file, which is defined by the [package.proto]
protobuf file.

Its purpose is to tell the recipe engine about this repo, and indicate any
other repos that this repo depends on (including precise dependency pins). All
recipe repos will need to depend on the 'recipe_engine' repo (the repo
containing this user_guide).

As part of this config, the repo needs an `id`, which should match the
LUCI-config project id for the repo; this id will show up when other recipe
repos depend on your repo.

Example [recipes.cfg](https://chromium.googlesource.com/chromium/tools/build/+/master/infra/config/recipes.cfg).

[package.proto]: /recipe_engine/package.proto

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

  * `__init__.py` - Contains the DEPS and PROPERTIES declarations for the
    recipe_module.
  * `api.py` - Contains the implementation of the recipe module.
  * `test_api.py` - Contains the implementation of the recipe module's fakes.

Example [recipe_modules folder](https://chromium.googlesource.com/chromium/tools/build/+/master/scripts/slave/recipe_modules).

#### The `recipes.py` script

The `recipes.py` script is the entrypoint to the recipe_engine. It's primary
functionality is to clone a copy of the recipe_engine repo (matching the version
in your `recipes.cfg` file), and then invoke the main recipe_engine code with
whatever command line you gave it.

This script invokes the recipe engine with `vpython`, which picks up a python
VirtualEnv suitable for the recipe engine (it includes things like
py-cryptography and the protobuf library).

### The `recipes.py` command

TODO(iannucci) - Document

### Writing recipes

TODO(iannucci) - Document

### Writing recipe_modules

TODO(iannucci) - Document

### Structured data passing for steps

TODO(iannucci) - Document

### Build UI manipulation

TODO(iannucci) - Document

### Testing recipes and recipe_modules

TODO(iannucci) - Document

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

**properties** -- A JSON object that every recipe is started with; These are
  the input parameters to the recipe.

**output properties** -- TODO(iannucci)

**PROPERTIES** -- An expression of a recipe or recipe_module of the properties
  that it relies on.
