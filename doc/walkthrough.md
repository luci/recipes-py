# Recipes

Recipes are a domain-specific language (embedded in Python) for specifying
sequences of subprocess calls in a cross-platform and testable way.

See [the user guide](./user_guide.md) for a general reference about the recipe
engine and ecosystem.

[TOC]

## Introduction

This README will seek to teach the ways of Recipes, so that you may do one or
more of the following:

  * Read them
  * Make new recipes
  * Fix bugs in recipes
  * Create libraries (recipe modules) for others to use in their recipes.

The document will build knowledge up in small steps using examples, and so it's
probably best to read the whole doc through from top to bottom once before using
it as a reference.

## Small beginnings

**Recipes are a means to cause a series of commands to run on a machine.**

All recipes take the form of a python file whose body looks like this:

```python
# scripts/slave/recipes/hello.py
DEPS = ['recipe_engine/step']

def RunSteps(api):
  api.step('Print Hello World', ['echo', 'hello', 'world'])

def GenTests(api):
  return ()
```

The `RunSteps` function is expected to take at least a single argument `api`
(we'll get to that in more detail later), and run a series of steps by calling
api functions. All of these functions will eventually make calls to
`api.step()`, which is the only way to actually get anything done on the
machine. Using python libraries with OS side-effects is prohibited to enable
testing.

The `GenTests` function currently does nothing, but a recipe is invalid and
cannot be run unless it defines a `GenTests` function.

For these examples we will work out of the
[tools/build](https://chromium.googlesource.com/chromium/tools/build/)
repository.

Put this in a file under `scripts/slave/recipes/hello.py`. You can then
run this recipe by calling

    $ scripts/slave/recipes.py run hello

*** promo
Note: every recipe execution (e.g. build) emits
a step log called `run_recipe` on the `setup_build` step which provides
a precise invocation for `recipes.py` correlating exactly with the current
recipe invocation. This is useful to locally repro a failing build without
having to guess at the parameters to `recipes.py`.
***

## We should probably test as we go...

**All recipes MUST have corresponding tests, which achieve 100% code coverage.**

You can execute the tests for the recipes by running

    $ scripts/slave/recipes.py test run

As part of running the tests the coverage of the recipes is checked, so you
should expect output similar to the following snippet to appear as part of the
output of the command.

    Name                             Stmts   Miss  Cover   Missing
    --------------------------------------------------------------
    scripts/slave/recipes/hello.py       5      1    80%   5
    --------------------------------------------------------------
    TOTAL                            21132      1    99%

    488 files skipped due to complete coverage.

    FATAL: Insufficient coverage (99%)
    ----------------------------------------------------------------------
    Ran 1940 tests in 61.135s

    FAILED

The Stmts column indicates the number of statements that are in the recipe file.
The Miss column indicates the number of statements that do not have coverage.
The Missing column details the spans of code that are not covered, so currently
only the statement on line 4 is not covered. The other statements are the DEPS
and function definitions and the body of the `GenTests`.

So let's add a test to get the necessary coverage.

```python
# scripts/slave/recipes/hello.py
DEPS = ['recipe_engine/step']

def RunSteps(api):
  api.step('Print Hello World', ['echo', 'hello', 'world'])

def GenTests(api):
  yield api.test('basic')
```

The `GenTests` method takes a single parameter `api` that has methods for
defining test specifications. Calling `GenTests` must result in an iterable of
test specifications. `api.test('basic')` creates a test specification that
causes a test case to be generated named 'basic' that has no input parameters.
As your recipe becomes more complex, you'll need to add more tests to make sure
that you maintain 100% code coverage.

If you were to run the tests at this point, you would now get a failure
including the following output.

    hello.basic failed:
    --- expected
    +++ actual
    @@ -1 +1,15 @@
    -None
    +[
    +  {
    +    "cmd": [
    +      "echo",
    +      "hello",
    +      "world"
    +    ],
    +    "name": "Print Hello World"
    +  },
    +  {
    +    "name": "$result",
    +    "recipe_result": null,
    +    "status_code": 0
    +  }
    +]

Every test case has associated json files detailing the steps executed by the
recipe and the results of those actions. If the sequence of steps executed by
the recipe don't match the expected values in the json file then the test will
fail.

You can train the test by running

    $ scripts/slave/recipes.py test train --filter hello

> The `--filter` flag can be used when running or training the tests to limit
> the tests that are executed. For details on the format, pass the `-h` flag to
> either `test run` or `test train`. Coverage will not be checked when using the
> `--filter` flag.

Training the test will generate or update the json expectation files. There
should now be a file `scripts/slave/recipes/hello.expected.basic.json` in your
working copy with content matching the steps executed by the recipe.

```json
[
  {
    "cmd": [
      "echo",
      "hello",
      "world"
    ],
    "name": "Print Hello World"
  },
  {
    "name": "$result",
    "recipe_result": null,
    "status_code": 0
  }
]
```

When making actual changes, these json files should be included as part of your
commit and reviewed for correctness.

Running the tests now would result in a passing run, printing OK.

### But we can do better

In reality, the json expectation files are something of a maintenance burden and
they don't do an effective job of making it clear what is being tested. You
still may need to know how to train expectations if you're making modifications
to existing recipes and modules that already use expectation files, but new
tests should instead use the post-process api which enables making assertions on
the steps that were run.

This functionality is exposed to `GenTests` by calling `api.post_process`. This
method requires a single parameter that is a function that will perform the
checks. The provided function must take two parameters: `check` and
`step_odict`.

*   `check` is the function that performs the low-level check operation; it
    evaluates a boolean expression and if it's false it records it as a failure.
    When it records a failure, it also records the backtrace and the values of
    variables used in the expression to provide helpful context when the
    failures are displayed.
*   `step_odict` is an `OrderedDict` mapping step name to the step's dictionary.
    The dictionary for a step contains the same information that appears for the
    step in the json expectation files.

`api.post_process` accepts arbitrary additional positional and keyword arguments
and these will be forwarded on to the assertion function.

The function can return a filtered subset of `step_odict` or it can return None
to indicate that there are no changes to `step_odict`. Multiple calls to
`api.post_process` can be made and each of the provided functions will be called
in order with the `step_odict` that results from prior assertion functions.

Let's re-write our test to use the post-process api:

```python
# scripts/slave/recipes/hello.py
from recipe_engine.post_process import StepCommandRE, DropExpectation

DEPS = ['recipe_engine/step']

def RunSteps(api):
  api.step('Print Hello World', ['echo', 'hello', 'world'])

def GenTests(api):
  yield (
      api.test('basic')
      + api.post_process(StepCommandRE, 'Print Hello World',
                         ['echo', 'hello', 'world'])
      + api.post_process(DropExpectation)
  )
```

Yes, elements of a test specification are combined with `+` and it's weird.

The call that includes `StepCommandRE` will check that the step named
'Print Hello World' has as its list of arguments ['echo', 'hello', 'world']
(each element can actually be a regular expression that must match the
corresponding argument). The call with just DropExpectation doesn't check
anything, it just inhibits the test from outputting a JSON expectation file.

If you were to change the command list passed when using `StepCommandRE` so that
it no longer matched, you would get output similar to the following:

    hello.basic failed:
        CHECK(FAIL):
          .../infra/recipes-py/recipe_engine/post_process.py:224 - StepCommandRE()
            `check(_fullmatch(expected, actual))`
              expected: 'world2'
              actual: 'world'
        added .../build/scripts/slave/recipes/hello.py:14
          StepCommandRE('Print Hello World', ['echo', 'hello', 'world2'])

This output provides the following information: a backtrace rooted from the
entry-point into the assertion function to the failed check call, the value of
variables in the expression provided to check (evaluate the expression in the
check call rather than before so that you get more helpful output) and the
location where the assertion was added.

See the documentation of `post_process` in
[recipe_test_api.py](https://chromium.googlesource.com/infra/luci/recipes-py/+/master/recipe_engine/recipe_test_api.py)
for more details about the post-processing api and see
[post_process.py](https://chromium.googlesource.com/infra/luci/recipes-py/+/master/recipe_engine/post_process.py)
for information on the available assertion functions.

Tests should use the post-process api to make assertions about the steps under
test. Just as when writing tests under any other frameworks, be careful not to
make your assertions too strict or you run the risk of needing to update tests
due to unrelated changes. Tests should also make sure to pass `DropExpectation`
to the final call to `api.post_process` to avoid creating JSON expectation
files. It's important for that to be the last call to `api.post_process` because
the functions passed to any later calls will receive an empty step dict
otherwise.

## Let's do something useful

### Properties are the primary input for your recipes

In order to do something useful, we need to pull in parameters from the outside
world. There's one primary source of input for recipes, which is `properties`.
The `properties` object is provided by the `properties` api module.

This is now abstracted into the PROPERTIES top level declaration in your recipe.
You declare a dictionary of properties that your recipe accepts. The recipe
engine will extract the properties your recipe cares about from all the
properties it knows about, and pass them as arguments to your RunSteps function.

Let's see an example!

```python
# scripts/slave/recipes/hello.py
from recipe_engine.post_process import StepCommandRE, DropExpectation
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = {
    'target_of_admiration': Property(
        kind=str, help="Who you love and adore.", default="Chrome Infra"),
}

def RunSteps(api, target_of_admiration):
  verb = 'Hello %s'
  if target_of_admiration == 'DarthVader':
    verb = 'Die in a fire %s!'
  api.step('Greet Admired Individual', ['echo', verb % target_of_admiration])

def GenTests(api):
  yield (
      api.test('basic')
      + api.properties(target_of_admiration='Bob')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Hello Bob'])
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('vader')
      + api.properties(target_of_admiration='DarthVader')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Die in a fire DarthVader!'])
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('infra rocks')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Hello Chrome Infra'])
      + api.post_process(DropExpectation)
  )
```

The property list is a whitelist, so if the properties provided as inputs to the
current recipe run were

```python
{
  'target_of_admiration': 'Darth Vader',
  'some_other_chill_thing': 'so_chill',
}
```

then the recipe wouldn't know about the other `some_other_chill_thing` property
at all.

Note that properties without a default are required. If you don't want a
property to be required, just add `default=None` to the definition.

Each parameter to `RunSteps` besides the `api` parameter requires a matching
entry in the PROPERTIES dict.

To specify property values in a local run:

    script/slaves/recipes.py run <recipe-name> opt=bob other=sally

Or, more explicitly::

    script/slaves/recipes.py --properties-file <path/to/json>

Where `<path/to/json>` is a file containing a valid JSON `object` (i.e.
key:value pairs).

Note that we need to put a dependency on the 'recipe_engine/properties' module
in the DEPS because we use it to generate our tests, even though we don't
actually call the module in our code.
See this [crbug.com/532275](bug) for more info.

### Modules

There are all sorts of helper modules. They are found in the `recipe_modules`
directory alongside the `recipes` directory where the recipes go.

There are a whole bunch of modules which provide really helpful tools. You
should go take a look at them. `scripts/slave/recipes.py` is a
pretty helpful tool. If you want to know more about properties, step and path, I
would suggest starting with `scripts/slave/recipes.py doc`, and then delving
into the helpful docstrings in those helpful modules.

Notice the `DEPS` line in the recipe. Any modules named by string in DEPS are
'injected' into the `api` parameter that your recipe gets. If you leave them out
of DEPS, you'll get an AttributeError when you try to access them. The modules
are located primarily in `recipe_modules/`, and their name is their folder name.

The format of the strings in the DEPS entry depends on whether the depended-on
module is part of the current repo or a dependency repo (e.g. depot_tools or
recipe_engine for the build repo). Modules from dependency repos are specified
with the form `<repo-name>/<module-name>` as has been done for the `step` and
`properties` modules. Modules from the current repo are specified with just the
module name.

## Making modules

**Modules are for grouping functionality together and exposing it across
recipes.**

So now you feel like you're pretty good at recipes, but you want to share your
echo functionality across a couple recipes which all start the same way. To do
this, you need to add a module directory.

```
scripts/slave/recipe_modules/
  ...
  goma/
  halt/
  hello/
    __init__.py  # (Required) Contains optional `DEPS = list([other modules])`
    api.py       # (Required) Contains single required RecipeApi-derived class
    config.py    # (Optional) Contains configuration for your api
    *_config.py  # (Optional) These contain extensions to the configurations of
                 #   your dependency APIs
    examples/    # (Recommended) Contains example recipes that show how to
                 #   actually use the module
    tests/       # (Optional) Contains test recipes that can be used to test
                 #   individual behaviors of the module
  ...
```

First add an `__init__.py` with DEPS:

```python
# scripts/slave/recipe_modules/hello/__init__.py
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = {
    'target_of_admiration': Property(default=None),
}
```

And your api.py should look something like:

```python
# scripts/slave/recipe_modules/hello/api.py
from recipe_engine import recipe_api

class HelloApi(recipe_api.RecipeApi):
  def __init__(self, target_of_admiration, *args, **kwargs):
    super(HelloApi, self).__init__(*args, **kwargs)
    self._target = target_of_admiration

  def greet(self, default_verb=None):
    verb = default_verb or 'Hello %s'
    if self._target == 'DarthVader':
      verb = 'Die in a fire %s!'
    self.m.step('Greet Admired Individual',
                ['echo', verb % self._target])
```

Note that all the DEPS get injected into `self.m`. This logic is handled outside
of the object (i.e. not in `__init__`).

> Because dependencies are injected after module initialization, *you do not
> have access to injected modules in your APIs `__init__` method*!

And now, our refactored recipe:

```python
# scripts/slave/recipes/hello.py
from recipe_engine.post_process import StepCommandRE, DropExpectation

DEPS = [
    'hello',
    'recipe_engine/properties',
]

def RunSteps(api):
  api.hello.greet()

def GenTests(api):
  yield (
      api.test('basic')
      + api.properties(target_of_admiration='Bob')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Hello Bob'])
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('vader')
      + api.properties(target_of_admiration='DarthVader')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Die in a fire DarthVader!'])
      + api.post_process(DropExpectation)
  )
```

If you were to run or train the tests without the `--filter` flag at this point,
you would experience a failure due to missing coverage of the hello module.
Before running any of the tests the following will appear in the output:

    ERROR: The following modules lack test coverage: hello

And the coverage report will be as follows:

    Name                                        Stmts   Miss  Cover   Missing
    -------------------------------------------------------------------------
    scripts/slave/recipe_modules/hello/api.py      10      6    40%   6-7, 10-13
    -------------------------------------------------------------------------
    TOTAL                                       21147      6    99%

To get coverage for a module you need to put recipes with tests in the examples
or tests subdirectory of the module. So let's move our hello recipe into the
examples subdirectory of our module.

```python
# scripts/slave/recipe_modules/hello/examples/simple.py
from recipe_engine.post_process import StepCommandRE, DropExpectation

DEPS = [
    'hello',
    'recipe_engine/properties',
]

def RunSteps(api):
  api.hello.greet()

def GenTests(api):
  yield (
      api.test('basic')
      + api.properties(target_of_admiration='Bob')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Hello Bob'])
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('vader')
      + api.properties(target_of_admiration='DarthVader')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         ['echo', 'Die in a fire DarthVader!'])
      + api.post_process(DropExpectation)
  )
```

Training the tests again now results in 100% coverage.

## So how do I really write those tests?

The basic form of tests is:

```python
def GenTests(api):
  yield api.test('testname') + # other stuff
```

Some modules define interfaces for specifying necessary step data; these are
injected into `api` from `DEPS` similarly to how it works for `RunSteps`. There
are a few other methods available to `GenTests`'s `api`. Common ones include:

  * `api.properties(buildername='foo_builder')` sets properties as we have seen.
  * `api.platform('linux', 32)` sets the mock platform to 32-bit linux.
  * `api.step_data('Hello World', retcode=1)` mocks the `'Hello World'` step
  to have failed with exit code 1.

By default all simulated steps succeed, the platform is 64-bit linux, and
there are no properties. The `api.properties.generic()` method populates some
common properties for Chromium recipes.

The `api` passed to GenTests is confusingly **NOT** the same as the recipe api.
It's actually an instance of `recipe_test_api.py:RecipeTestApi()`. This is
admittedly pretty weak, and it would be great to have the test api
automatically created via modules. On the flip side, the test api is much less
necessary than the recipe api, so this transformation has not been designed yet.

## What is that config business?

**Configs are a way for a module to expose it's "global" state in a reusable
way.**

A common problem in Building Things is that you end up with an inordinately
large matrix of configurations. Let's take chromium, for example. Here is a
sample list of axes of configuration which chromium needs to build and test:

  * BUILD_CONFIG
  * HOST_PLATFORM
  * HOST_ARCH
  * HOST_BITS
  * TARGET_PLATFORM
  * TARGET_ARCH
  * TARGET_BITS
  * builder type (ninja? msvs? xcodebuild?)
  * compiler
  * ...

Obviously there are a lot of combinations of those things, but only a relatively
small number of *valid* combinations of those things. How can we represent all
the valid states while still retaining our sanity?

We begin by specifying a schema that configurations of the `hello` module
will follow, and the config context based on it that we will add configuration
items to.

```python
# scripts/slave/recipe_modules/hello/config.py
from recipe_engine.config import config_item_context, ConfigGroup
from recipe_engine.config import Single, Static, BadConf

def BaseConfig(TARGET='Bob'):
  # This is a schema for the 'config blobs' that the hello module deals with.
  return ConfigGroup(
    verb = Single(str),
    # A config blob is not complete() until all required entries have a value.
    tool = Single(str, required=True),
    # Generally, your schema should take a series of CAPITAL args which will be
    # set as StaticConfig data in the config blob.
    TARGET = Static(str(TARGET)),
  )

config_ctx = config_item_context(BaseConfig)
```

The `BaseConfig` schema is expected to return a `ConfigGroup` instance of some
sort. All the configs that you get out of this file will be a modified version
of something returned by the schema method. The arguments should have sane
defaults, and should be named in `ALL_CAPS` (this is to avoid argument name
conflicts as we'll see later).

`config_ctx` is the 'context' for all the config items in this file, and will
magically become the `CONFIG_CTX` for the entire module. Other modules may
extend this context, which we will get to later.

Finally let's define some config items themselves. A config item is a function
decorated with the `config_ctx`, and takes a config blob as 'c'. The config item
updates the config blob, perhaps conditionally. There are many features to
`slave/recipe_config.py`. I would recommend reading the docstrings there
for all the details.

```python
# scripts/slave/recipe_modules/hello/config.py

# ...

# Each of these functions is a 'config item' in the context of config_ctx.

# is_root means that every config item will apply this item first.
@config_ctx(is_root=True)
def BASE(c):
  if c.TARGET == 'DarthVader':
    c.verb = 'Die in a fire %s!'
  else:
    c.verb = 'Hello %s'

@config_ctx(group='tool')  # items with the same group are mutually exclusive.
def super_tool(c):
  if c.TARGET != 'Charlie':
    raise BadConf('Can only use super tool for Charlie!')
  c.tool = 'unicorn.py'

@config_ctx(group='tool')
def default_tool(c):
  c.tool = 'echo'
```

Now that we have our config, let's use it.

```python
# scripts/slave/recipe_modules/hello/api.py
from recipe_engine import recipe_api

class HelloApi(recipe_api.RecipeApi):
  def __init__(self, target_of_admiration, *args, **kwargs):
    super(HelloApi, self).__init__(*args, **kwargs)
    self._target = target_of_admiration

  def get_config_defaults(self):
    defaults = {}
    if self._target is not None:
      defaults['TARGET'] = self._target
    return defaults

  def greet(self, default_verb=None):
    self.m.step('Greet Admired Individual', [
        self.m.path['start_dir'].join(self.c.tool),
        self.c.verb % self.c.TARGET])
```

Note that `recipe_api.RecipeApi` contains all the plumbing for dealing with
configs. If your module has a config, you can access its current value via
`self.c`. The users of your module (read: recipes) will need to set this value
in one way or another. Also note that c is a 'public' variable, which means that
recipes have direct access to the configuration state by `api.<modname>.c`.

```python
# scripts/slave/recipe_modules/examples/simple.py
from recipe_engine.post_process import StepCommandRE, DropExpectation

DEPS = [
    'hello',
    'recipe_engine/properties',
]

def RunSteps(api):
  api.hello.set_config('default_tool')
  api.hello.greet()

def GenTests(api):
  yield (
      api.test('bob')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         [r'.*\becho', 'Hello Bob'])
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('anya')
      + api.properties(target_of_admiration='anya')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         [r'.*\becho', 'Hello anya'])
      + api.post_process(DropExpectation)
  )
```

Note the call to `set_config`. This method takes the configuration name
specified, finds it in the given module (`'hello'` in this case), and sets
`api.hello.c` equal to the result of invoking the named config item
(`'default_tool'`) with the default configuration (the result of calling
`get_config_defaults`), merged over the static defaults specified by the schema.

Note that the first pattern provided when using StepCommandRE is now
`r'.*\becho'`. Because we are using the path module to locate the tool now, the
command line no longer has just echo. The patterns must match the entire
argument (this simplifies the case of matching against most constant strings),
so the `r'.*\b'` matches any number of leading characters and then a word
boundary so that we match a tool named 'echo' in some location.

100% coverage is required for `config.py` also, so lets add some additional
examples that call `set_config` differently to get different results:

```python
# scripts/slave/recipe_modules/examples/rainbow.py
from recipe_engine.post_process import StepCommandRE, DropExpectation

DEPS = ['hello']

def RunSteps(api):
  api.hello.set_config('super_tool', TARGET='Charlie')
  api.hello.greet()  # Greets 'Charlie' with unicorn.py.

def GenTests(api):
  yield (
      api.test('charlie')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         [r'.*\bunicorn.py', 'Hello Charlie'])
      + api.post_process(DropExpectation)
  )
```

```python
# scripts/slave/recipe_modules/examples/evil.py
from recipe_engine.post_process import StepCommandRE, DropExpectation

DEPS = ['hello']

def RunSteps(api):
  api.hello.set_config('default_tool', TARGET='DarthVader')
  api.hello.greet()  # Causes 'DarthVader' to despair with echo

def GenTests(api):
  yield (
      api.test('darth')
      + api.post_process(StepCommandRE, 'Greet Admired Individual',
                         [r'.*\becho', 'Die in a fire DarthVader!'])
      + api.post_process(DropExpectation)
  )
```

`set_config()` also has one additional bit of magic. If a module (say,
`chromium`), depends on some other modules (say, `gclient`), if you do
`api.chromium.set_config('blink')`, it will apply the `'blink'` config item from
the chromium module, but it will also attempt to apply the `'blink'` config for
all the dependencies, too. This way, you can have the chromium module extend the
gclient config context with a 'blink' config item, and then `set_configs` will
stack across all the relevant contexts. (This has since been recognized as a
design mistake)

`recipe_api.RecipeApi` also provides `make_config` and `apply_config`, which
allow recipes more-direct access to the config items. However, `set_config()` is
the most-preferred way to apply configurations.

We still don't have coverage for the line in config.py that raises a `BadConf`.
This isn't an example of how the `hello` module should be used, so lets add a
recipe under the tests subdirectory to get the last bit of coverage.

```python
# scripts/slave/recipe_modules/hello/tests/badconf.py
from recipe_engine.post_process import DropExpectation

DEPS = ['hello']

def RunSteps(api):
  api.hello.set_config('super_tool', TARGET='Not Charlie')

def GenTests(api):
  yield (
      api.test('badconf')
      + api.expect_exception('BadConf')
      + api.post_process(DropExpectation)
  )
```

## What about getting data back from a step?

Consider this recipe:

```python
# scripts/slave/recipes/shake.py
from recipe_engine.post_process import DropExpectation, MustRun

DEPS = [
    'recipe_engine/path',
    'recipe_engine/step',
]

def RunSteps(api):
  step_result = api.step(
      'Determine blue moon',
      [api.path['start_dir'].join('is_blue_moon.sh')],
      ok_ret='any')

  if step_result.retcode == 0:
    api.step('HARLEM SHAKE!',
             [api.path['start_dir'].join('do_the_harlem_shake.sh')])
  else:
    api.step('Boring',
             [api.path['start_dir'].join('its_a_small_world.sh')])

def GenTests(api):
  yield (
      api.test('harlem')
      + api.step_data('Determine blue moon', retcode=0)
      + api.post_process(MustRun, 'HARLEM SHAKE!')
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('boring')
      + api.step_data('Determine blue moon', retcode=1)
      + api.post_process(MustRun, 'Boring')
      + api.post_process(DropExpectation)
  )
```

The `ok_ret` parameter to `api.step()` is necessary if you wish to react to a
step's retcode. By default, any retcode except 0 will result in an exception.
Pass one of the strings 'any' or 'all' to continue execution regardless of the
retcode. Alternatively you can pass a tuple or set of ints to continue execution
if the step's retcode is one of the provided values.

See how we use `step_result` to get the result of the last step? The item we get
back is a `recipe_engine.main.StepData` instance (really, just a basic object
with member data). The members of this object which are guaranteed to exist are:
  * `retcode`: Pretty much what you think
  * `step`: The actual step JSON which was sent to `annotator.py`. Not usually
    useful for recipes, but it is used internally for the recipe tests
    framework.
  * `presentation`: An object representing how the step will show up on the
    build page, including its exit status, links, and extra log text. This is a
    `recipe_engine.main.StepPresentation` object.
    See also
    [How to change step presentation](#how-to-change-step-presentation).

This is pretty neat... However, it turns out that returncodes suck bigtime for
communicating actual information. `api.json.output()` to the rescue!

```python
# scripts/slave/recipes/war.py
from recipe_engine.post_process import DropExpectation, MustRun

DEPS = [
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/step',
]

def RunSteps(api):
  step_result = api.step(
      'run tests',
      [api.path['start_dir'].join('do_test_things.sh'), api.json.output()])
  num_passed = step_result.json.output['num_passed']
  if num_passed > 500:
    api.step('victory', [api.path['start_dir'].join('do_a_dance.sh')])
  elif num_passed > 200:
    api.step('not defeated', [api.path['start_dir'].join('woohoo.sh')])
  else:
    api.step('deads!', [api.path['start_dir'].join('you_r_deads.sh')])

def GenTests(api):
  yield (
      api.test('winning')
      + api.step_data('run tests', api.json.output({'num_passed': 791}))
      + api.post_process(MustRun, 'victory')
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('not_dead_yet')
      + api.step_data('run tests', api.json.output({'num_passed': 302}))
      + api.post_process(MustRun, 'not defeated')
      + api.post_process(DropExpectation)
  )

  yield (
      api.test('noooooo')
      + api.step_data('run tests', api.json.output({'num_passed': 10}))
      + api.post_process(MustRun, 'deads!')
      + api.post_process(DropExpectation)
  )
```

### How does THAT work!?

`api.json.output()` returns a `recipe_api.Placeholder` which is meant to be
added into a step command list. When the step runs, the placeholder gets
rendered into some strings (in this case, like '/tmp/some392ra8'). When the step
finishes, the [Placeholder](#placeholders) adds data to the `StepData` object
for the step which just ran, namespaced by the module name (in this case, the
'json' module decided to add an 'output' attribute to the `step_history` item).
I'd encourage you to take a peek at the implementation of the json module to see
how this is implemented.

### Example: write to standard input of a step

```python
api.step(..., stdin=api.raw_io.input('test input'))
```

Also see [raw_io's
example](https://chromium.googlesource.com/chromium/tools/build.git/+/master/scripts/slave/recipe_modules/raw_io/examples/full.py).

### Example: read standard output of a step as json

```python
step_result = api.step(..., stdout=api.json.output())
data = step_result.stdout
# data is a parsed JSON value, such as dict
```

Also see [json's
example](https://chromium.googlesource.com/chromium/tools/build.git/+/master/scripts/slave/recipe_modules/json/examples/full.py).

### Example: write to standard input of a step as json

```python
data = {'value': 1}
api.step(..., stdin=api.json.input(data))
```

Also see [json's
example](https://chromium.googlesource.com/chromium/tools/build.git/+/master/scripts/slave/recipe_modules/json/examples/full.py).

### Example: simulated step output

This example specifies the standard output that should be returned when
a step is executed in simulation mode. This is typically used for
specifying default test data in the recipe or recipe module and removes
the need to specify too much test data for each test in GenTests:

```python
api.step(..., step_test_data=api.raw_io.output('test data'))
```

### Example: simulated step output for a test case

```python
yield (
    api.test('my_test') +
    api.step_data(
        'step_name',
        output=api.raw_io.output('test data')))
```

## How to change step presentation?

`step_result.presentation` allows modifying the appearance of a step:

### Logging

```python
step_result.presentation.logs['mylog'] = ['line1', 'line2']
```

Creates an extra log "mylog" under the step.

### Setting properties

Input properties (`api.properties`) are immutable, but you can add so-called output properties in a step, like this:

```python
step_result.presentation.properties['newprop'] = 1
```

### Example: step text

This modifies the text displayed next to a step name:

```python
step_result = api.step(...)
step_result.presentation.step_text = 'Dynamic step result text'
```

* `presentation.logs` allows creating extra logs of a step run. Example:
  ```python
  step_result.presentation.logs['mylog'] = ['line1', 'line2']
  ```
* presentation.properties allows changing and adding new output properties:
  ```python
  step_result.presentation.properties['newprop'] = 1
  ```

## How do I know what modules to use?

Use `scripts/slave/recipes.py doc`. It's super effective!

## How do I run those tests you were talking about?

Each repo has a recipes.py entry point under `recipes_path` from `recipes.cfg` .

Execute the following commands:
`./recipes.py test run`
`./recipes.py test train`

Specifically, for `tools/build` repo, the commands to execute are:
`scripts/slave/recipes.py test run`
`scripts/slave/recipes.py test train`

## Where are the docs for recipes and modules?

Documentation for recipes is done with Python docstrings. For convenience,
these docstrings may be extracted and formatted in a README.recipes.md file.

In addition, most recipe modules have example recipes in the `examples`
subfolder which exercises most of the code in the module for example purposes.

## <a name="placeholders"></a>  What are Placeholders and how do they work?

Placeholders are wrappers around inputs and outputs from recipe steps. They
provide a mocking mechanism for tests, and data-processing capabilities.

### Example

```python
step_result = api.python('run a cool script', 'really_cool_script.py',
                         ['--json-output-file', api.json.output()],
                         ok_ret=(0,1))
print step_result.json.output
```

There's quite a bit of magic happening underlying these two lines of code. Let's
dive in.

`api.json.output()` returns an instance of `JsonOutputPlaceholder`.
`JsonOutputPlaceholder` is a subclass of `OutputPlaceholder`, and has two
relevant public methods: `render()` and `result()`. The recipe engine will
replace each instance of `OutputPlaceholder` in the arguments list with
`OutputPlaceholder.render()`. `JsonOutputPlaceholder` creates a file and returns
its name in `render()`. For this example, let's assume that `render()` returns
`/tmp/output.json`.

So in this case, the recipe engine will actually execute:
```
python really_cool_script.py --json-output-file /tmp/output.json
```

When the program returns, the recipe engine will call
`JsonOutputPlaceholder.result()` and seed the result into
`step_result.json.output`. Here, `json` refers to the name of the recipe module,
and `output` was the name of the function that returned the
`JsonOutputPlaceholder`.

The implementation of `JsonOutputPlaceholder.result()` will parse the JSON from
`/tmp/output.json`.

### Tests and Mocks

```python
yield api.test('test really_cool_script.py') +
api.step_data('run a cool script', api.json.output({'json': 'object'}))
```

This test case will stub out the actual invocation of `really_cool_script.py`
and directly populate the test dictionary into
`api.step.active_result.json.output`.

Behind the scenes, this works because the `json` module has defined a
`test_api.py` class with a method `output`. The invocation of `api.json.output`
is actually calling a different function than the prior call to
`api.json.output`.
