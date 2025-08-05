# Style
Google Python style, 80 column limit

Commit messages should have the module name or recipe prefix instead of
something like `fix:` or `[fix]`
- Yes: `[futures] Fix spelling error`
- No: `fix: Fix spelling error`

Recipe testing often requires `test_data` or `step_test_data` arguments in what
otherwise looks like production code—leave these arguments alone.

Setting properties on a `StepPresentation` modifies global data, so don't remove
apparent no-ops that just modify a `properties` member of an object.

Don't include comments on import lines.

Don't have any trailing whitespace at the end of lines.

The `RunSteps()` function in a recipe gets passed an `api` object of type
`recipe_api.RecipeScriptApi`. Any additional arguments relate to the
`PROPERTIES` global variable. It returns `RawResult | None`.

The `GenTests()` function in a recipe gets passed an `api` object of type
`recipe_test_api.RecipeTestApi` and it returns
`Iterator[recipe_test_api.TestData]`.

All recipes must define both `RunSteps()` and `GenTests()`.

Indentation in docstrings should be independent of the length of the variable
name.
- Yes:
  Args:
      very_long_variable_name: Description takes
        multiple lines.
- No:
  Args:
      very_long_variable_name: Description takes
                               multiple lines.

Don't import individual classes or variables—always import modules, and never
use `from <module> import *`.  Exceptions:
- from collections.abc import <type>
- from typing import <type>
- from PB.<module> import foo as foo_pb

All imports should be at top-level, even if they`re only used in GenTests()

When importing a module under `PB`, import `as <module>_pb`.
- Yes: from PB.recipe_engine import result as result_pb
- No: from PB.recipe_engine import result

# Module Dependencies
Aside from the Python standard library and third party packages, recipes don't
share code via imports. Instead, shared recipe code is defined in a recipe
module under the recipe_modules directory. A recipe can import a recipe module
by listing the module in its DEPS list. Then the module will be accessible via
the `api` object that's passed to RunSteps.

For example, a call to a `api.foo.bar()` function in a recipe's `RunSteps`
function calls the `bar` method of an object of the `recipe_api.RecipeApi`
subclass defined in `recipe_modules/foo/api.py`. Any recipe module that a
recipe calls must also be listed in the recipe's `DEPS` variable, e.g.
`DEPS = ["recipe_engine/foo"]`.

In a recipe module, dependencies are injected via the `self.m` object instead of
`api`, but it works the same way - `self.m.foo.bar()` calls the `foo` recipe
module's `bar` method. The dependencies of recipe module `foo` are listed in the
`DEPS` variable in `recipe_modules/foo/__init__.py`.

On the other hand, a call to `api.foo.bar()` in a `GenTests` function refers to
the `bar` method in `recipe_modules/foo/test_api.py`. `test_api.py` files
provide helper functions for mocking results of various recipe steps.

If necessary, modules themselves can be imported with lines like this:
`from RECIPE_MODULES.<repo-name>.<mod-name> import api as <mod-name>_api`.
Prefer this structure over other ways to import modules directly.

Types defined in a recipe module should be included in the
`recipe_api.RecipeApi` subclass. This makes it easier to reference these types
outside of the module for annotations. Do not do this for types not part of the
module's API. Example:

```
  class FooData:
    pass
   
  class FooApi(recipe_api.RecipeApi):
    FooData = FooData
   
    def __init__(self, *args, **kwargs):
      ...
```

# Python Type Annotations
Use `from __future__ import annotations` in all files.

Use `list` and `dict` instead of `typing.List` and `typing.Dict`.

Function and method arguments should use generic types if possible, like
`Sequence` or `Mapping`.

Return values should use specific types, like `list` or `dict`.

When there are suitable types in both `typing` and `collections.abc`, use the
type from `collections.abc`.

Don't use `import typing` and then using `typing.TypeName` everywhere. Instead,
use `from typing import TypeName`. The same rule applies to `collections.abc`
imports. If there are too many types to fit on one line, put each imported type
on it's own line.

Don't hide type annotation imports under `if typing.TYPE_CHECKING:`. Exception
for imports that begin with `RECIPE_MODULES` and the corresponding module is not
included in DEPS.

Make sure any `if TYPE_CHECKING:` lines that do exist have a
`# pragma: no cover` comment.

Only create `TypeVar` variables just before they're used.

Don't use `Optional[T]` or `Union[T1, T2]`. Instead, use `T | None` or
`T1 | T2`.

# Testing
After making a change, run `./recipes.py test train --stop` to check that
everything still works. If making many changes, wait to run this until the end.
