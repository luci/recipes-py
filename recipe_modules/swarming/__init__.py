# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.recipe_modules.recipe_engine.swarming import properties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'buildbucket',  # TODO(crbug.com/1122808): Remove this dependency.
    'cas',
    'cipd',
    'context',
    'isolated',
    'json',
    'path',
    'properties',
    'raw_io',
    'runtime',
    'step',
]

PROPERTIES = properties.InputProperties
ENV_PROPERTIES = properties.EnvProperties
