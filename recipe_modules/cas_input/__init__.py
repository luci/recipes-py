# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.recipe_modules.recipe_engine.cas_input import properties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'path',
    'cas',
]

PROPERTIES = properties.InputProperties
