# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.cq.api.recipe.v1 import cq as cq_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

from recipe_engine import recipe_test_api


class CQTestApi(recipe_test_api.RecipeTestApi):
  def __call__(
      self,
      full_run=None, dry_run=None,
      top_level=True,
      experimental=False,
      gerrit_changes=None):
    """Simulate a build triggered by CQ."""
    if full_run:
      assert not dry_run, ('either `dry` or `full` run, not both')
      assert isinstance(full_run, bool), '%r (%s)' % (full_run, type(full_run))
      input_props = cq_pb2.Input(active=True, dry_run=False)
    elif dry_run:
      assert isinstance(dry_run, bool), '%r (%s)' % (dry_run, type(dry_run))
      input_props = cq_pb2.Input(active=True, dry_run=True)
    else:
      # TODO(tandrii): disallow this. api.cq() should simulate CQ build.
      return self.m.properties()

    assert isinstance(top_level, bool), '%r (%s)' % (top_level, type(top_level))
    input_props.top_level = top_level

    assert isinstance(experimental, bool), '%r (%s)' % (
        experimental, type(experimental))
    input_props.experimental = experimental

    if gerrit_changes:
      for gcl in gerrit_changes:
        assert isinstance(gcl, bb_common_pb2.GerritChange), (type(gcl), gcl)
        cl = input_props.cls.add()
        cl.gerrit.CopyFrom(gcl)

    return self.m.properties(**{'$recipe_engine/cq': input_props})
