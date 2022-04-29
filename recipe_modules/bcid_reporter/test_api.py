# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api

class BcidReporterTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def pid(pid):
    """Set the process id for the current test.
    """
    assert isinstance(pid, int), ('bad pid (not integer): %r' % (pid,))
    return pid

  def __call__(self, pid):
    return (self.pid(pid))
