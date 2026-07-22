# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from typing import Iterator

from recipe_engine import post_process, recipe_api, recipe_test_api

DEPS = [
    'assertions',
    'cipd',
    'path',
]


def RunSteps(api: recipe_api.RecipeScriptApi) -> None:
  ef_default = api.cipd.EnsureFile()
  api.assertions.assertEqual(
      ef_default.paranoid_mode,
      None,
  )
  ef_default.add_package('pkg/default', 'latest')
  api.assertions.assertEqual(
      ef_default.render(),
      'pkg/default latest',
  )

  ef_presence = (
      api.cipd.EnsureFile()
      .add_package('pkg/foo', 'latest')
      .with_paranoid_mode(api.cipd.ParanoidMode.CHECK_PRESENCE)
  )
  api.assertions.assertEqual(
      ef_presence.paranoid_mode,
      api.cipd.ParanoidMode.CHECK_PRESENCE,
  )
  api.assertions.assertEqual(
      ef_presence.render(),
      '$ParanoidMode CheckPresence\npkg/foo latest'
  )

  ef_integrity = (
      api.cipd.EnsureFile()
      .add_package('pkg/baz', 'latest')
      .with_paranoid_mode(api.cipd.ParanoidMode.CHECK_INTEGRITY)
  )
  api.assertions.assertEqual(
      ef_integrity.paranoid_mode,
      api.cipd.ParanoidMode.CHECK_INTEGRITY,
  )
  api.assertions.assertEqual(
      ef_integrity.render(),
      '$ParanoidMode CheckIntegrity\npkg/baz latest',
  )

  cipd_root = api.path.start_dir / 'packages'
  api.cipd.ensure(cipd_root, ef_presence)
  api.cipd.ensure_file_resolve(ef_integrity)


def GenTests(
    api: recipe_test_api.RecipeTestApi,
) -> Iterator[recipe_test_api.TestData]:
  yield api.test(
    'basic',
    api.post_process(post_process.DropExpectation),
  )
