# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    file,
    json,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  file: file.API
  json: json.API
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  src = api.path.start_dir / 'some file'
  data = 'Here is some text data'

  api.file.write_text('write a file', src, data)
  api.file.symlink('symlink it', src, api.path.start_dir / 'new path')
  read_data = api.file.read_text(
    'read it', api.path.start_dir / 'new path', test_data=data)

  assert read_data == data, (read_data, data)


  # Also create a tree of symlinks.
  root = api.path.cleanup_dir / 'root'
  tree = api.file.symlink_tree(root)
  assert root == tree.root
  # It is okay to register the same pair multiple times.
  tree.register_link(src, root / 'another' / 'symlink')
  tree.register_link(src, root / 'another' / 'symlink')
  src2 = api.path.start_dir / 'a-second-file'
  tree.register_link(src2, root / 'yet' / 'another' / 'symlink')
  tree.create_links('create a tree of symlinks')


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
