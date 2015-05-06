Recipes
=======
Recipes are a flexible way to specify How to Do Things, without knowing too much
about those Things.


Background
----------

Chromium uses BuildBot for its builds.  It requires master restarts to change
bot configs, which slows bot changes down.

With Recipes, most build-related things happen in scripts that run on the
slave, which reduces the number of master restarts needed when changing build
configuration.

Intro
-----
This README will seek to teach the ways of Recipes, so that you may do one or
more of the following:

  * Read them
  * Make new recipes
  * Fix bugs in recipes
  * Create libraries (api modules) for others to use in their recipes.

The document will build knowledge up in small steps using examples, and so it's
probably best to read the whole doc through from top to bottom once before using
it as a reference.


Small Beginnings
----------------
**Recipes are a means to cause a series of actions to occur on a machine.**

All recipes take the form of a python file whose body looks like this:

```python
def GenSteps(api):
  yield {
      'name': 'Hello World',
      'cmd': ['/b/build/echo.sh', 'hello', 'world']
  }
```

The GenSteps function is expected to take a single argument `api` (we'll get to
that in more detail later), and yield a series of 'stepish' items. A stepish
item can be:

  * A single step (a dictionary as in the example above)
  * A series (list or tuple) of stepish items
  * A python-generator of stepish items


We should probably test as we go...
-----------------------------------
**All recipes MUST have corresponding tests, which achieve 100% code coverage.**

So, we have our recipe. Let's add a test to it.

```python
def GenSteps(api):
  yield {
      'name': 'Hello World',
      'cmd': ['/b/build/echo.sh', 'hello', 'world']
  }

def GenTests(api):
  yield 'basic', {}
```

This causes a single test case to be generated, called 'basic', which has no
input parameters.  As your recipe becomes more complex, you'll need to add more
tests to make sure that you maintain 100% code coverage.


Let's do something useful
-------------------------
**Properties is the primary input for your recipes.**

In order to do something useful, we need to pull in parameters from the outside
world. There's one primary source of input for recipes, which is `properties`.

`properties` are a relic from the days of BuildBot, though they have been
dressed up a bit to be more like we'll want them in the future. If you're
familiar with BuildBot, you'll probably know them as `factory_properties` and
`build_properties`. The new `properties` object is a merging of these two, and
is provided by the `properties` api module.

```python
DEPS = ['properties']

def GenSteps(api):
  verb = 'Hello, %s'
  target = api.properties['target_of_admiration']
  if target == 'DarthVader':
    verb = 'Die in a fire, %s!'
  yield {'name': 'Hello World', 'cmd': ['/b/build/echo.sh', verb % target]}

def GenTests(api):
  yield 'basic', {
    'properties': {'target_of_admiration': 'Bob'}
  }

  yield 'vader', {
    'properties': {'target_of_admiration': 'DarthVader'}
  }
```

Ok, I lied. It wasn't very useful.


Let's make it a bit prettier
----------------------------
**You can add modules to your recipe by simply adding them to DEPS.**

So there are all sorts of helper modules. I'll add in the 'step' and 'path'
modules here as an example.

```python
DEPS = ['properties', 'step', 'path']

def GenSteps(api):
  verb = 'Hello, %s'
  target = api.properties['target_of_admiration']
  if target == 'DarthVader':
    verb = 'Die in a fire, %s!'
  yield api.step('Hello World', [api.path['build'].join('echo.sh'),
                 verb % target])

def GenTests(api):
  yield 'basic', {
    'properties': {'target_of_admiration': 'Bob'}
  }

  yield 'vader', {
    'properties': {'target_of_admiration': 'DarthVader'}
  }
```

Notice the `DEPS` line in the recipe. Any modules named by string in DEPS are
'injected' into the `api` parameter that your recipe gets. If you leave them out
of DEPS, you'll get an AttributeError when you try to access them. The modules
are located primarily in `recipe_modules/`, and their name is their folder name.

> The full list of module locations which get added are in `recipe_util.py` in
> the `MODULE_DIRS` variable.

There are a whole bunch of modules which provide really helpful tools. You
should go take a look at them. `show_me_the_modules.py` is a pretty helpful
tool. If you want to know more about properties, step and path, I would suggest
starting with `show_me_the_modules.py`, and then delving into the docstrings in
those modules.


Making Modules
--------------
**Modules are for grouping functionality together and exposing it across
recipes.**

So now you feel like you're pretty good at recipes, but you want to share your
echo functionality across a couple recipes which all start the same way. To do
this, you need to add a module directory.

```
recipe_modules/
  step/
  properties/
  path/
  hello/
    __init__.py  # (Required) Contains optional `DEPS = list([other modules])`
    api.py       # (Required) Contains single required RecipeApi-derived class
    config.py    # (Optional) Contains configuration for your api
    *_config.py  # (Optional) These contain extensions to the configurations of
                 #   your dependency APIs
```

First add an `__init__.py` with DEPS:

```python
# recipe_modules/hello/__init__.py
DEPS = ['properties', 'path', 'step']
```

And your api.py should look something like:

```python
from slave import recipe_api

class HelloApi(recipe_api.RecipeApi):
  def greet(self, default_verb=None, target=None):
    verb = default_verb or 'Hello %s'
    target = target or self.m.properties['target_of_admiration']
    if target == 'DarthVader':
      verb = 'Die in a fire %s!'
    yield self.m.step('Hello World',
                      [self.m.path.build('echo.sh'), verb % target])
```

See that all the DEPS get injected into `self.m`. This logic is handled outside
of the object (i.e. not in `__init__`) in the loading function creatively named
`load_recipe_modules()`, which resides in `recipe_api.py`.

> Because dependencies are injected after module initialization, *you do not have
> access to injected modules in your APIs `__init__` method*!

And now, our refactored recipe:

```python
DEPS = ['hello']

def GenSteps(api):
  yield api.hello.greet()

def GenTests(api):
  yield 'basic', {
    'properties': {'target_of_admiration': 'Bob'}
  }

  yield 'vader', {
    'properties': {'target_of_admiration': 'DarthVader'}
  }
```

> NOTE: all of the modules are also under code coverage, but you only need some
> test SOMEWHERE to cover each line.


So how do I really write those tests?
-------------------------------------
**Tests are yielded as a (name, test data) tuple.**

The basic form of tests is:
```python
def GenTests(api):
  yield 'testname', {
    # Test data
  }
```

Test data can contain any of the following keys:
  * *properties*: This represents the merged factory properties and build
    properties which will show up as api.properties for the duration of the
    test. This dictionary is in simple `{<prop name>: <prop value>}` form.
  * *mock*: Some modules need to have their behavior altered before the recipe
    starts. For example, you could mock which platform is being tested, or mock
    which paths exist. This dictionary is in the form of `{<mod name>: <mod
    data>}`. See module docstrings to see what they accept for mocks.
  * *step_mocks*: This is a dictionary which defines the mock data for
    various `recipe_api.Placeholder` objects. These are explained more in
    a later section.  This dictionary is in the form of `{<step name>: {<mod
    name>: <mod data>}}`
    * There is one 'special' mod name, which is '$R'. This module refers to the
      return code of the step, and takes an integer. If it is missing, it is
      assumed that the step succeeded with a retcode of 0.

The `api` passed to GenTests is confusingly **NOT** the same as the recipe api.
It's actually an instance of `recipe_test_api.py:RecipeTestApi()`. This is
admittedly pretty weak, and it would be great to have the test api
automatically created via modules. On the flip side, the test api is much less
necessary than the recipe api, so this transformation has not been designed yet.


What is that config business?
-----------------------------
**Configs are a way for a module to expose it's "global" state in a reusable
way.**

A common problem in Building Things is that you end up with an inordinantly
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

```python
# recipe_modules/hello/config.py
from slave.recipe_config import config_item_context, ConfigGroup
from slave.recipe_config import SimpleConfig, StaticConfig, BadConf

def BaseConfig(TARGET='Bob'):
  # This is a schema for the 'config blobs' that the hello module deals with.
  return ConfigGroup(
    verb   = SimpleConfig(str),
    # A config blob is not complete() until all required entries have a value.
    tool   = SimpleConfig(str, required=True),
    # Generally, your schema should take a series of CAPITAL args which will be
    # set as StaticConfig data in the config blob.
    TARGET = StaticConfig(str(TARGET)),
  )

VAR_TEST_MAP = {
  'TARGET':   ('Bob', 'DarthVader', 'Charlie'),
}
config_ctx = config_item_context(BaseConfig, VAR_TEST_MAP, '%(TARGET)s')

# Each of these functions is a 'config item' in the context of config_ctx.

# is_root means that every config item will apply this item first.
@config_ctx(is_root=True)
def BASE(c):
  if c.TARGET == 'DarthVader':
    c.verb = 'Die in a fire, %s!'
  else:
    c.verb = 'Hello, %s'

@config_ctx(group='tool'):  # items with the same group are mutually exclusive.
def super_tool(c):
  if c.TARGET != 'Charlie':
    raise BadConf('Can only use super tool for Charlie!')
  c.tool = 'unicorn.py'

@config_ctx(group='tool'):
def default_tool(c):
  c.tool = 'echo.sh'
```

Ok, this config file looks a bit intimidating. Let's decompose it. The first
portion is the schema `BaseConfig`. This is expected to return a ConfigGroup
instance of some sort. All the configs that you get out of this file will be
a modified version something returned by the schema method. The arguments should
have sane defaults, and should be named in `ALL_CAPS` (this is to avoid argument
name conflicts as we'll see later).

The `VAR_TEST_MAP` is a mapping of argument name for the schema (in this case,
just 'TARGET'), to a sequence of values to test. The test harness will
automatically generate the product of all arguments in this map, and will run
through each config function in the file to generate the expected config blob
for each. In this config, it would essentially be:

```python
for TARGET in ('Bob', 'DarthVader', 'Charlie'):
  for test_function in (super_tool, default_tool):
    yield TestCase(test_function(BasicSchema(TARGET)))
```

Next, we get to the `config_ctx`. This is the 'context' for all the config
items in this file, and will become the `CONFIG_CTX` for the entire module.
Other modules may add into this config context (for example, they could have
a `hello_config.py` file, which imports this config context like

```python
import DEPS
CONFIG_CTX = DEPS['hello'].CONFIG_CTX
```


This will be useful for separation of concerns with the `set_config()`
method.). The string format argument that `config_item_context` takes will be
used to format the test case names and test expectation file names. Not
terribly useful here, but it can be useful for making the test names more
obvious in more complex cases.

Finally we get to the config items themselves. A config item is a function
decorated with the `config_ctx`, and takes a config blob as 'c'. The config item
updates the config blob, perhaps conditionally. There are many features to
`slave/recipe_config.py`. I would recommend reading the docstrings there
for all the details.

Now that we have our config, let's use it.

```python
# recipe_modules/hello/api.py
from slave import recipe_api

class HelloApi(recipe_api.RecipeApi):
  def get_config_defaults(self, _config_name):
    return {'TARGET': self.m.properties['target_of_admiration']}

  def greet(self):
    yield self.m.step('Hello World', [
        self.m.path.build(self.c.tool), self.c.verb % self.c.TARGET])
```

Note that `recipe_api.RecipeApi` contains all the plumbing for dealing with
configs. If your module has a config, you can access its current value via
`self.c`. The users of your module (read: recipes) will need to set this value
in one way or another. Also note that c is a 'public' variable, which means that
recipes have direct access to the configuration state by `api.<modname>.c`.

```python
# recipes/hello.py
DEPS = ['hello']
def GenSteps(api):
  api.hello.set_config('default_tool')
  yield api.hello.greet()  # Greets 'target_of_admiration' or 'Bob' with echo.sh.

def GenTests(api):
  yield 'bob', {}
  yield 'anya', {'properties': {'target_of_admiration': 'anya'}}
```

Note the call to `set_config`. This method takes the configuration name
specifed, finds it in the given module (`'hello'` in this case), and sets
`api.hello.c` equal to the result of invoking the named config item
(`'default_tool'`) with the default configuration (the result of calling
`get_config_defaults`), merged over the static defaults specified by the schema.
In this case, the schema will be initialized by essentially the following calls:

```python
raw = BaseConfig(**api.hello.get_config_defaults())
api.hello.c = default_tool(BASE(raw))
```

We can also call `set_config` differently to get different results:

```python
# recipes/rainbow_hello.py
DEPS = ['hello']
def GenSteps(api):
  api.hello.set_config('super_tool', TARGET='Charlie')
  yield api.hello.greet()  # Greets 'Charlie' with unicorn.py.

def GenTests(api):
  yield 'charlie', {}
```

```python
# recipes/evil_hello.py
DEPS = ['hello']
def GenSteps(api):
  api.hello.set_config('default_tool', TARGET='DarthVader')
  yield api.hello.greet()  # Causes 'DarthVader' to despair with echo.sh

def GenTests(api):
  yield 'darth', {}
```

`set_config()` also has one additional bit of magic. If a module (say,
chromium), depends on some other modules (say, gclient), if you do
`api.chromium.set_config('blink')`, it will apply the 'blink' config item from
the chromium module, but it will also attempt to apply the 'blink' config for
all the dependencies, too. This way, you can have the chromium module extend the
gclient config context with a 'blink' config item, and then set_configs will
stack across all the relevent contexts.

`recipe_api.RecipeApi` also provides `make_config` and `apply_config`, which
allow recipes more-direct access to the config items. However, `set_config()` is
the most-preferred way to apply configurations.


What about getting data back from a step?
-----------------------------------------
**If you need you recipe to be conditional on something that a step does, you'll
need to make use of the `step_history` api.**

Consider this recipe:
```python
DEPS = ['step', 'path', 'step_history']

def GenSteps(api):
  yield api.step('Determine blue moon', [api.path['build'].join('is_blue_moon.sh')])
  if api.step_history.last_step().retcode == 0:
    yield api.step('HARLEM SHAKE!', [api.path['build'].join('do_the_harlem_shake.sh')])
  else:
    yield api.step('Boring', [api.path['build'].join('its_a_small_world.sh')])

def GenTests(api):
  yield 'harlem', {
    'step_mocks': {'Determine blue moon': {'$R': 0}}
  }
  yield 'boring', {
    'step_mocks': {'Determine blue moon': {'$R': 1}}
  }
```

See how we use `step_history` to get the result of the last step? The item we
get back is an `annotated_run.RecipeData` instance (really, just a basic object
with member data). The members of this object which are guaranteed to exist are:
  * retcode: Pretty much what you think
  * step: The actual step json which was sent to `annotator.py`. Not usually
    useful for recipes, but it is used internally for the recipe tests
    framework.

This is pretty neat... However, it turns out that returncodes suck bigtime for
communicating actual information. `api.json.output()` to the rescue!

```python
DEPS = ['step', 'path', 'step_history', 'json']

def GenSteps(api):
  yield api.step('run tests', [
    api.path['build'].join('do_test_things.sh'), api.json.output()])
  num_passed = api.step_history.last_step().json.output['num_passed']
  if num_passed > 500:
    yield api.step('victory', [api.path['build'].join('do_a_dance.sh')])
  elif num_passed > 200:
    yield api.step('not defeated', [api.path['build'].join('woohoo.sh')])
  else:
    yield api.step('deads!', [api.path['build'].join('you_r_deads.sh')])

def GenTests(api):
  yield 'winning', {
    'step_mocks': {'run tests': {'json': {'output': {'num_passed': 791}}}}
  }
  yield 'not_dead_yet', {
    'step_mocks': {'run tests': {'json': {'output': {'num_passed': 302}}}}
  }
  yield 'nooooo', {
    'step_mocks': {'run tests': {'json': {'output': {'num_passed': 10}}}}
  }
```

How does THAT work!?

`api.json.output()` returns a `recipe_api.Placeholder` which is meant to be
added into a step command list. When the step runs, the placeholder gets
rendered into some strings (in this case, like `['--output-json',
'/tmp/some392ra8'`]). When the step finishes, the Placeholder is allowed to add
data to the step history for the step which just ran, namespaced by the module
name (in this case, the 'json' module decided to add an 'output' attribute to
the `step_history` item). I'd encourage you to take a peek at the implementation
of the json module to see how this is implemented.


How do I know what modules to use?
----------------------------------
Use `tools/show_me_the_modules.py`. It's super effective!


How do I run those tests you were talking about?
------------------------------------------------
To test all the recipes/apis, use `slave/unittests/recipe_simulation_test.py`.
To set new expectations `slave/unittests/recipe_simulation_test.py train`.



Where's the docs on `*.py`?
--------------------------------------------
Check the docstrings in `*.py`. `<trollface text="Problem?"/>`

In addition, most recipe modules have an `example.py` file which exercises most
of the code in the module for both test coverage and example purposes.

If you want to know what keys a step dictionary can take, take a look at
`common/annotator.py`.

