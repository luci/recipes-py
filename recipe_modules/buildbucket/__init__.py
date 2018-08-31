# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'json',
  'platform',
  'properties',
  'raw_io',
  'runtime',
  'step',
]

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
  '$recipe_engine/buildbucket': Property(
      help='Internal property to initialize buildbucket module',
      param_name='property',
      kind=ConfigGroup(
          # base64-encoded bytes of buildbucket.v2.Build message serialized as
          # binary. Serialized to discourage users from interpreting it,
          # and to ignore unrecognized fields.
          # Exposed as buildbucket.build property, see its docstring.
          build=Single(str),
      ),
      default={},
  ),

  # === Legacy =================================================================
  'buildbucket': Property(param_name='legacy_property', default={}),

  'mastername': Property(default=None),
  'buildername': Property(default=None),
  'buildnumber': Property(default=None),

  # sources for buildbucket.build.input.gitiles_commit.
  'repository': Property(default=None),
  'branch': Property(default=None),
  'revision': Property(default=None),

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
