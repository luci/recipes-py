# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'json',
  'path',
  'platform',
  'properties',
  'raw_io',
  'runtime',
  'step',
  'uuid',
]

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Dict, Single

PROPERTIES = {
  '$recipe_engine/buildbucket': Property(
      help='Internal property to initialize buildbucket module',
      param_name='property',
      kind=ConfigGroup(
          hostname=Single(basestring),
          # A dict representing a JSONPB-encoded buildbucket.v2.Build message.
          # DO NOT USE DIRECTLY IN RECIPES!
          # Use api.buildbucket.build instead, see its docstring.
          build=Dict(),
      ),
      default={},
  ),

  # === Legacy =================================================================
  'buildbucket': Property(param_name='legacy_property', default={}),

  'mastername': Property(default=None),
  'buildername': Property(default=None),
  'buildnumber': Property(default=None),

  # sources for buildbucket.build.input.gitiles_commit.
  'revision': Property(default=None),
  'parent_got_revision': Property(default=None),
  'branch': Property(default=None),

  # sources for buildbucket.build.input.gerrit_changes.
  'patch_storage': Property(default=None),
  'patch_gerrit_url': Property(default=None),
  'patch_project': Property(default=None),
  'patch_issue': Property(default=None),
  'patch_set': Property(default=None),
  'issue': Property(default=None),
  'patchset': Property(default=None),
  # ============================================================================
}
