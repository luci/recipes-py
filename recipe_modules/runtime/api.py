# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api


class RuntimeApi(recipe_api.RecipeApi):
  """This module assists in experimenting with production recipes.

  For example, when migrating builders from Buildbot to pure LUCI stack.
  """

  def __init__(self, properties, **kwargs):
    super(RuntimeApi, self).__init__(**kwargs)
    self._properties = properties

  @property
  def is_luci(self):
    """True if this recipe is currently running on LUCI stack.

    Should be used only during migration from Buildbot to LUCI stack.
    """
    return bool(self._properties.get('is_luci', False))

  @property
  def is_experimental(self):
    """True if this recipe is currently running in experimental mode.

    Typical usage is to modify steps which produce external side-effects so that
    non-production runs of the recipe do not affect production data.

    Examples:
      * Uploading to an alternate google storage file name when in non-prod mode
      * Appending a 'non-production' tag to external RPCs
    """
    return bool(self._properties.get('is_experimental', True))
