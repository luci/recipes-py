# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class CQTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, full_run=None, dry_run=None):
    """Simulate a build triggered by CQ."""
    if full_run:
      assert not dry_run, ('either dry or full run, not both')
      assert isinstance(full_run, bool), '%r (%s)' % (full_run, type(full_run))
      props = {'dry_run': False}
    elif dry_run:
      assert isinstance(dry_run, bool), '%r (%s)' % (dry_run, type(dry_run))
      props = {'dry_run': True}
    else:
      props = {}
    ret = self.test(None)
    ret.properties = {'$recipe_engine/cq': props}
    return ret
