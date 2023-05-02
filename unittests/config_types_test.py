#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import test_env

from recipe_engine import config_types


class TestConfigGroupSchema(test_env.RecipeEngineUnitTest):

  def testPathJoin(self):
    base_path = config_types.Path(config_types.NamedBasePath('base'))
    reference_path = base_path.join('foo').join('bar')
    self.assertEqual(base_path / 'foo' / 'bar', reference_path)


if __name__ == '__main__':
  test_env.main()
