# Recipe Engine Unit Tests

This directory contains all the 'unit' tests for the recipe engine. In reality
this folder contains a mix of unit and integration tests. All of the tests in
here use the `test_env` module (in this directory). This module provides a base
unittest.TestCase class with some helpers.

The main helpers are `FakeRecipeDeps` and `MockRecipeDeps`.

## test_env.RecipeEngineUnitTest

This is the base unittest class for all tests in this directory. It has some
nice common functionality:

  * `maxDiff` is always set to None (meaning that large test failures will
    always show the full diff).
  * If you pass '-v' on the command line, it will enable verbose logging.
  * If you pass '--leak' on the command line, it will leak all temporary files
    and directories from tests which fail. This can be useful for debugging the
    state of a test.
  * tempfile and tempdir functions for easy auto-cleaned temporary stuff.
  * assertDictEqual and assertListEqual have been updated to strip out all the
    unicode objects from their arguments (replacing them with str), which means
    that the diffs from test failures are actually helpful.

## MockRecipeDeps

This is a lightweight 'mocked' version of recipe_deps.RecipeDeps. It contains
only in-memory constructs which imitate the APIs exposed by the real RecipeDeps.

Currently this is pretty bare-bones and only covers the needs of e.g. the
tests for the `analyze` command (and friends). If you're writing new unit tests,
please opt to extend this mocked version and use it directly.

## FakeRecipeDeps

This is a very heavyweight 'fake' framework for writing recipe integration
tests. It manipulates the state of real git repos on disk with the following
layout:

     tmpdir/
       main/           # the main 'entrypoint' repo for the FakeRecipeDeps.
         recipes.py    # you'll usually call this with the recipes_py function
         .recipe_deps/ # contains (local) clones of all of main's dependencies
           depname/
         infra/config/recipes.cfg
         ....
       sources/
         depname/   # the "upstream repo" location

You may notice that there are two copies of `depname`. The one in `sources` is
analogous to the 'remote repository' (i.e. the one on googlesource.com), whereas
the one in `main/.recipe_deps` is the 'local clone' of a real recipe repo.

Of course, all of these repos are local and very small. This testing setup
allows testing even relatively complex features like `autoroll`, which require
fetching the 'remote' changes into the 'local' .recipe_deps.
