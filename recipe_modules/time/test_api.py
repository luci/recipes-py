# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_test_api

class TimeTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def seed(now):
    return now

  @recipe_test_api.mod_test_data
  @staticmethod
  def step(step):
    return step
