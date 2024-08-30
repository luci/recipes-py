# Recipe engine implementation details

This doc covers implementation details of the recipe engine and its processes.
Read this if you want to understand/modify how the recipes as a system work. For
general recipe development, please see [user_guide.md](./user_guide.md).

[TOC]


## Recipe engine subcommands

All recipe engine subcommands live in the [commands] folder. The `__init__.py`
file here contains the entry point for all subcommand parsing `parse_and_run`
which is invoked from [main.py].

The commands module contains (as submodules) all of the subcommands that the
recipe engine supports. The protocol is pretty simple:

  * The subcommand lives in a submodule (either directory or .py file).
  * Each submodule has a `add_arguments(parser)` function (for directories, this
    is expected to be in the `__init__.py` file).
  * Each submodule may also define an optional `__cmd_priority__` field. This
    should be an integer which will be used to rank commands (e.g. so that 'run'
    and 'test' can precede all other subcommands). Commands will be ordered
    first by __cmd_priority__ (lower values sort earlier) and then
    alphabetically. This is currently used to put `run` and `test` as the
    topmost arguments in the `recipes.py` help output.
  * The `add_arguments` function takes an argparse parser, and adds flags to it.
    The parser will be created:
    * using the module's name as the command name
    * using the module's `__doc__` to generate both the description and 'help'
      for the parser (help will be the first paragraph of `__doc__`).
  * In addition to adding flags, the function must also call:

      ```
      parser.set_defaults(
          postprocess_func=function(error, args), # optional
          func=function(args))                    # required
      ```

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

This section talks about how the recipe engine gets from the recipes.py
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
  * A `recipes` folder - contains entry point scripts (recipes) for the repo.
  * A `recipe_modules` folder - contains modules which may be depended on (used
    by) both recipe scripts as well as other modules (in this repo and any other
    repos which depend on it).

Additionally, `recipes.cfg` describes dependencies with a git URL, commit
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
(with git) all dependencies described in `recipes.cfg`. Every dependency
will be checked out at `$recipes_path/.recipe_deps/$dep_name`.

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
files in 4 places in a repo:
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
  * `repo_name` | `NUL` - The name of the repo.

Then, for every .proto in the repo we hash:
  * `relative_path_in_repo` | `NUL`
  * `relative_path_of_global_destination` | `NUL`
  * `githash_of_content` | `NUL`

The `githash_of_content` is defined by git's "blob" hashing scheme (but is
currently implemented in pure Python).

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
    loading regular python modules.
  * `RECIPE_MODULES.repo_name.module_name....` - All submodules are imported
    without any alteration using `imp.find_module` and `imp.load_module`.


### Recipe loading

Recipe loading is substantially simpler than loading modules. The recipe `.py`
file is exec'd with
[`execfile`](https://docs.python.org/2/library/functions.html#execfile), and
then it's PROPERTIES dict (if any) is bound the same way as it is for Recipe
Modules.

### Instantiating '**api**' objects

Now that we know how to load the __code__ for modules and recipes, we need to
actually instantiate them. This process starts at the recipe's `DEPS`
description, and walks down the entire DEPS tree, instantiating recipe modules
on the way back up (so, they're instantiated in topological order from bottom to
top of the dependency tree).

Instantiation can either be done in 'API' mode or 'TEST_API' mode. 'API' mode is
to generate the `api` object which is passed to `RunSteps`. 'TEST_API' mode is
to generate the `api` object which is passed to `GenTests`. Both modes traverse
the dependency graph the same way, but 'API' mode does a superset of the work
(since all `RecipeApi` objects have a reference to their `test_api` as
`self.test_api`).

Both `RecipeTestApi` and `RecipeApi` classes have an `m` member injected
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
subclass is instantiated by calling its `__init__` and then injecting its `m`
object.

If the loader is in 'API' mode, then the module's RecipeApiPlan subclass is also
instantiated, using the declared PROPERTIES as arguments to __init__, along with
`test_data`, which may be provided if the `api` is being used from the
`recipes.py test` subcommand to provide mock data for the execution of the test.
The `m` object is injected, and then any `UnresolvedRequirement` objects are
injected as well.  Finally, after `m` has been injected and all
`UnresolvedRequirement` objects are injected, the loader calls the instance's
`initialize()` method to allow it to do post-dependency initialization.

*** note
The `UnresolvedRequirement` objects are currently only used to provide limited
'pinhole' interfaces into the recipe engine, such as the ability to run
a subprocess (step), or get access to the global properties that the recipe was
started with, etc. Typically these are only used by a single module somewhere in
the `recipe_engine` repo; user recipe modules are not expected to use these.
***

## Simulation tests

This section talks about the code that implements the test command of
recipes.py.

### Post-process hooks

As part of the definition of a simulation test, the user can add post-process
hooks to filter and/or make assertions on the expectations recorded for the test
run. Hooks can be added using either the `post_process` or `post_check` methods
of RecipeTestApi. The code that runs these hooks as well as the implementation
of the `check` callable passed as the first argument to hooks is located in
[magic_check_fn.py].

The `check` callable passed to post-process hooks is an instance of `Checker`.
The `Checker` class is responsible for recording failed checks, including
determining the relevant stack frames to be included in the failure output.

The `Checker` is instantiated in `post_process` and assigned to a local
variable. The local variable is important because the `Checker` object uses the
presence of itself in the frame locals to define the boundary between engine
code and post-process hook code. In the event of a failure, the `Checker`
iterates over the stack frames, starting from the outermost frame and proceeding
towards the current execution point. The first frame where the `Checker` appears
in the frame locals is the last frame of engine code and the relevant frames
begin starting at the next frame and excluding the 2 innermost frames (the
`__call__` method calls `_call_impl` which is where the frame walking takes
place.

Failures may also be recorded in the case of a KeyError. KeyErrors are caught in
`post_process` and the frames to be included in the failure are extracted from
the exception info.

Once relevant frames are determined by `Checker` or `post_process`,
`Check.create` is called to create a representation of the failure containing
processed frames. The frames are converted to `CheckFrame`, a representation
that holds information about the point in code that the frame refers to without
keeping all of the frame locals alive.

Processing a frame involves extracting the filename, line number and function
name from the frame and where possible reconstructing the expression being
evaluated in that frame. To reconstruct the expression, `CheckFrame` maintains a
cache that maps filename and line number to AST nodes corresponding to
expressions whose definitions end at that line number. The end line is the line
that will appear as the line number of a frame executing that expression. The
cache is populated by parsing the source code into nodes and then examining the
nodes. Nodes that define expressions or simple statements (statements that can't
have additional nested statements) are added to the cache. Other statements
result in nested statements or expressions being added to the queue. When a
simple statement or expression is added to the cache, we also walk over all of
its nested nodes to find any lambda definitions. Lambda definitions within a
larger expression may result in line numbers in an execution frame that doesn't
correspond with the line number of the larger expression, so in order to display
code for frames that occur in lambdas we add them to the cache separately.

In the case of the innermost frame, the `CheckFrame` also includes information
about the values of the variables and expressions relevant for determining the
exact nature of the check failure. `CheckFrame` has a varmap field that is a
dict mapping a string representation for a variable or expression to the value
of that variable or expression (e.g. 'my_variable' -> 'foo'). The expression
may not be an expression that actually appears in the code if the expression
would actually be more useful than the actual expression in the code (e.g.
`some_dict.keys()` will appear if the call `check('x' in some_dict)` fails
because the values in `some_dict` aren't relevant to whether `'x'` is in it).
This varmap is constructed by the `_checkTransformer` class, which is a
subclass of `ast.NodeTransformer`. `ast.NodeTransformer` is an instance of the
visitor design pattern containing methods corresponding to each node subclass.
These methods can be overridden to modify or replace the nodes in the AST.

`_checkTransformer` overrides some of these methods to replace nodes with
resolved nodes where possible. Resolved nodes are represented by `_resolved`, a
custom node subclass that records a string representation and a value for a
variable or expression. It also records whether the node is valid. The node
would not be valid if the recorded value doesn't correspond to the actual value
in the code, which is the case if we replace an expression with an expression
more useful for the user (e.g. showing only the keys of a dict when a membership
check fails). The node types handled by `_checkTransformer` are:

  * `Name` nodes correspond to a variable or constant and have the following
    fields:
    * `id` - string that acts as a key into one of frame locals, frame globals
      or builtins
    If `id` is one of the constants `True`, `False` and `None` the node is
    replaced with a resolved node with the name of the constant as the
    representation and the constant itself as the value. Otherwise, if the name
    is found in either the frame locals or the frame globals, the node is
    replaced with a resolved node with `id` as the representation and the looked
    up value as the value.
  * `Attribute` nodes correspond to an expression such as `x.y` and  have the
    following fields:
    * `value` - node corresponding to the expression an attribute is looked up
      on (`x`)
    * `attr` - string containing the attribute to look up (`y`)
    If `value` refers to a resolved node, then we have been able to resolve the
    preceding expression and so we replace the node with a resolved node with
    the value of the lookup.
  * `Compare` nodes correspond to an expression performing a series of
    comparison operations and have the following fields:
    * `left` - node corresponding the left-most argument of the comparison
    * `ops` - sequence of nodes corresponding to the comparison operators
    * `cmps` - sequence of nodes corresponding to the remaining arguments of the
      comparison
    The only change we make to `Compare` nodes is to prevent the full display of
    dictionaries when a membership check is performed; if the expression
    `x in y` fails when y is a dict, we do not actually care about the values of
    `y`, only its keys. If `ops` has only a single element that is an instance
    of either `ast.In` or `ast.NotIn` and `cmps` has only a single element that
    is a resolved node referring to a dict, then we make a node that replaces
    the `cmps` with a single resolved node with the dict's keys as its value.
    The new resolved node is marked not valid because we wouldn't expect
    operations that work against the dict to necessarily work against its keys.
  * `Subscript` nodes correspond to an expression such as `x[y]` and contains
    the following fields:
    * `value` - node corresponding to the expression being indexed (`x`)
    * `slice` - node corresponding to the subscript expression (`y`), which may
      be a simple index, a slice or an ellipsis
    If `value` is a valid resolved node and `slice` is a simple index (instance
    of `ast.Index`), then we attempt to create a resolved node with the value of
    the lookup as its value. We don't attempt a lookup if the `value` is an
    invalid resolved node because we would expect the lookup to raise an
    exception or return a different value then the actual code would. In the
    case that we do perform the lookup, it still may fail (e.g.
    `check('x' in y and y['x'] == 'z')` when 'x' is not in `y`). If the lookup
    fails and `value` is a dict, then we return a new invalid resolved node with
    the dict's keys as its value so that the user has some helpful information
    about what went wrong.

The nodes returned by the transformer are walked to find the resolved nodes and
the varmap is populated mapping the resolved nodes' representations to their
values that have been rendered in a user-friendly fashion.

## How recipes are run

Once the recipe is loaded, the running subcommand (i.e. `run`, `test`,
`luciexe`) selects a [StreamEngine] and a [StepRunner]. The StreamEngine is
responsible for exporting the state of the running recipe to the outside world,
and the StepRunner is responsible for running steps (or simulating them for
tests).

Once the subcommand has selected the relevant engine and runner, it then hands
control off to `RecipeEngine.run_steps`, which orchestrates the actual execution
of the recipe (namely; running steps, handling errors and updating presentation
via the StreamEngine).

### StreamEngine

The StreamEngine's responsibility is to accept reports about the UI and data
export ("output properties") state of the recipe, and channel them to an
appropriate backend service which can render them. The UI backend is the LUCI
service called "Milo", which runs on https://ci.chromium.org.

There are 2 primary implementations of the StreamEngine; one for the old
`@@@annotation@@@` protocol, and another which directly emits [build.proto] via
logdog.

The entire recipe engine was originally written to support the
`@@@annotation@@@` protocol, and thus StreamEngine is very heavily informed by
this. It assumes that all data is 'append only', and structures things as
commands to a backend, rather than setting state on a persistent object and
assuming that the StreamEngine will worry about state replication to the
backend.

The 'build.proto' (LUCI) engine maps the command-oriented StreamEngine interface
onto a persistent `buildbucket.v2.Build` protobuf message, and then replicates
the state of this message to the backend via 'logdog' (which is LUCI's log
streaming service).

Going forward the plan is to completely remove the `@@@annotation@@@` engine in
favor of the LUCI engine.

### StepRunner

The StepRunner's responsibility is to translate between the recipe and the
operating system (and by extension, anything outside of the memory of the
process executing the recipe). This includes things like mediating access to the
filesystem and actually executing subprocesses for steps. This interface is
currently an ad-hoc collection of functions pertaining to the particulars of how
recipes work today (i.e. the `placeholder` methods returning test data).

*** note
TODO:
Give StepRunner a full vfs-style interface; Instead of doing weird mocks in the
path module for asserting that files exist, and having placeholder-specific
data, the user could manipulate the state of the filesystem in their test and
then the placeholders would be implemented against the (virtual) filesystem
directly.
***

There are two implementations of the StepRunner; A "real" implementation and
a "simulation" implementation.

The real implementation actually talks to the real filesystem and executes
subprocesses when asked for the execution result of steps.

The simulation implementation supplies responses to the RecipeEngine for
placeholder test data and step results.

One feature of the StepRunner implementations is that they don't raise
exceptions; In particular the 'run' function should return an ExecutionResult
even if the step crashes, doesn't exist or whatever other terrible condition
it may have.

### Running steps

Within a chunk of recipe user code, steps are executed sequentially. When a step
runs (i.e. the recipe user code invokes `api.step(...)`), a number of things
happens:

  1. Inform the StepRunner that we're about to run the step
  1. Create a new `step_stream` with the StreamEngine so the UI knows about the
     step.
  1. Open a debug log '$debug'. The progress of the engine running the step will
     be recorded here, along with any exceptions raised.
  1. Open a log "$execution details" which contains all the data associated with
     running the step (command, env, etc.) and also the final exit code of the
     step.
  1. The engine renders all input placeholders attached to the step. This
     typically involves writing data to disk (but it depends on the placeholder
     implementation).
  1. The engine runs the step to get an ExecutionResult.
  1. The step's "initial status" is calculated. This is a function of running
     the step (its ExecutionResult) and also properties like `ok_ret` and
     `infra_step`.
  1. The output placeholders are resolved.

If an exception is raised during this process it's logged (to `$debug`) and then
saved while the engine does the final processing.

Currently, when a step has finished execution, its `step_stream` is kept open
and the step is pushed onto a stack of `ActiveStep`s. Depending on the
configuration of the step (`ok_ret`, `infra_step`, etc.) the engine will raise
an exception back into user code. If something broke while running the step (like
a bad placeholder, or the user asked to run a non-executable file... you know,
the usual stuff), this exception will be re-raised after the engine finalizes
the StepData, and sets up the presentation status (likely, "EXCEPTION").

#### Drawbacks of current presentation/exception handling implementation.

However, the step remains open until **the next step runs!**

The step's presentation can be accessed, _and modified_ in a couple ways:
  * Via the return value of `api.step()`
  * Via the '.result' property of the caught StepFailure exception.
  * Via the magical `api.step.active_result` property.

The first one isn't too bad, but the last two are pretty awful. This means that
a user of your module function can get access to your step result and:
  * Modify the presentation of your step
    * (not too bad, though kinda weird... if the changes they make to your step
      don't mesh well with your own changes it'll look like you goofed something
      up).
  * Directly read the data results of your step's placeholders.
    * Change your implementation to use 2 placeholders instead of one? Surprise!
      You've now broken all your downstream users.
    * This is pretty bad.
  * Read the output properties from your step!
    * Hey! Those were supposed to be write-only! What the heck?

[build.proto]: https://chromium.googlesource.com/infra/luci/luci-go/+/master/buildbucket/proto/build.proto
[commands]: /recipe_engine/internal/commands
[engine]: /recipe_engine/internal/engine.py
[magic_check_fn.py]: /recipe_engine/internal/test/magic_check_fn.py
[main.py]: /recipe_engine/main.py
[PEP302]: https://www.python.org/dev/peps/pep-0302/
[proto_support.py]: /recipe_engine/internal/proto_support.py
[recipe_module_importer.py]: /recipe_engine/internal/recipe_module_importer.py
[recipes.py]: /recipes.py
[recipes_cfg.proto]: /recipe_engine/recipes_cfg.proto
[simple_cfg.py]: /recipe_engine/internal/simple_cfg.py
[StepRunner]: /recipe_engine/internal/step_runner/__init__.py
[StreamEngine]: /recipe_engine/internal/stream/__init__.py
