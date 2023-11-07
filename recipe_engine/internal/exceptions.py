# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Defines all explicitly raised exception types for the recipe engine."""


class RecipeUsageError(Exception):
  """Base exception class for all errors raised due to some misuse of the
  recipes system (i.e. a problem with a user's recipe repo, recipe code, module
  code, etc.)

  Caught by the recipe engine in `run.py`.
  """

class RecipeLoadError(RecipeUsageError):
  """Raised when loading a recipe raises a non-syntax exception."""

class RecipeSyntaxError(SyntaxError, RecipeUsageError):
  """Raised when a recipe has invalid syntax."""

class MalformedRecipeError(RecipeUsageError):
  """Raised when a recipe doesn't contain RunSteps + GenTests."""

class MalformedModuleError(RecipeUsageError):
  """Raised when a recipe module does not contain proper Api or TestApi."""

class CyclicalDependencyError(RecipeUsageError):
  """Raised when a module depends on itself (possibly transitively)."""

class UnknownRepoName(RecipeUsageError, KeyError):
  """Raised when an unknown repo_name is referenced."""

class UnknownRecipeModule(RecipeUsageError, KeyError):
  """Raised when an unknown recipe module is referenced."""

class UnknownRecipe(RecipeUsageError, KeyError):
  """Raised when an unknown recipe is referenced."""

class UndefinedPropertyException(RecipeUsageError):
  """Raised when invoking a RunSteps or RecipeApi constructor where the
  arguments don't match the PROPERTIES for that invocation."""

class BadProtoDefinitions(RecipeUsageError):
  """Raised when multiple repos have the same .proto file."""


class RecipeEngineError(Exception):
  """Base exception class for all errors due to an error within the recipe
  engine."""

class GitFetchError(RecipeEngineError):
  """Raised when recipe_engine.internal.fetch.GitBackend fails a git
  invocation."""

class UnresolvedRefspec(RecipeEngineError):
  """Raised from fetch.Backend.assert_resolved if the given revision is,
  in fact, not resolved."""


### BaseException-derived exceptions.

class CrashEngine(BaseException):
  """Raised from the engine when the user-provided functions (like step
  callbacks) raise an exception.

  This exception should only be handled by the recipe engine.
  """
  def __init__(self, reason):
    super(CrashEngine, self).__init__(reason)
    self.reason = reason
