# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'json',
  'platform',
  'properties',
  'raw_io',
  'step',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
  'buildername': Property(default=None),
  'buildnumber': Property(default=None),
}
