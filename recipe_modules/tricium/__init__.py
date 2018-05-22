# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'json',
  'properties',
  'step',
]

from recipe_engine.config import List, Enum
from recipe_engine.recipe_api import Property

PROPERTIES = {
  'repository':
    Property(kind=str, help='Repository to checkout', default=None),
  'ref':
    Property(kind=str, help='Gerrit patch ref', default=None),
  'paths':
    Property(kind=List(basestring), help='Paths to files in ref', default=[]),
}
