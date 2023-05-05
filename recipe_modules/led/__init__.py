# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'cipd',
  'context',
  'json',
  'path',
  'proto',
  'step',
  'swarming',
]

from PB.recipe_modules.recipe_engine.led import properties

PROPERTIES = properties.InputProperties
