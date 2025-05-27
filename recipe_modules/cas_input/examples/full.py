# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'cas_input',
    'path',
    'properties',
]

from PB.recipe_modules.recipe_engine.cas_input.properties import InputProperties, CasCache

from recipe_engine.post_process import StepSuccess, StepCommandContains, DropExpectation


def RunSteps(api):
  if dd := api.properties.get('download_dir'):
    download_dir = api.path.abs_to_path(dd)
  else:
    download_dir = api.path.start_dir
  api.cas_input.download_caches(download_dir)


def GenTests(api):

  def cas_props(input_properties, download_dir=None):
    props = {
        '$recipe_engine/cas_input': input_properties,
    }
    if download_dir:
      props['download_dir'] = download_dir
    return api.properties(**props)

  yield api.test(
      'basic', cas_props(InputProperties(caches=[CasCache(digest='deadbeef')])))

  yield api.test(
      'download_to_directory',
      cas_props(
          InputProperties(caches=[CasCache(digest='deadbeef')]),
          download_dir='[TMP_BASE]'),
      api.post_process(StepSuccess, 'download cache'),
      api.post_process(StepCommandContains, 'download cache', '[TMP_BASE]'),
      api.post_process(DropExpectation))

  yield api.test(
      'rel_path',
      cas_props(
          InputProperties(
              caches=[CasCache(digest='deadbeef', local_relpath='some_path')])),
      api.post_process(StepSuccess, 'download cache'),
      api.post_process(StepCommandContains, 'download cache',
                       '[START_DIR]/some_path'),
      api.post_process(DropExpectation))
