# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import Filter

DEPS = [
  'recipe_engine/archive',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]


def RunSteps(api):
  # Prepare directories.
  out = api.path.start_dir.joinpath('output')
  api.file.rmtree('cleanup', out)
  api.file.ensure_directory('mkdirs out', out)

  temp = api.path.mkdtemp('tar-example')

  # Make a bunch of files
  api.step('touch a', ['echo', 'hello a'],
           stdout=api.raw_io.output(leak_to=temp.joinpath('a')))
  api.step('touch b', ['echo', 'hello b'],
           stdout=api.raw_io.output(leak_to=temp.joinpath('b')))
  api.file.ensure_directory('mkdirs sub/dir', temp.joinpath('sub', 'dir'))
  api.step('touch c', ['echo', 'hello c'],
           stdout=api.raw_io.output(leak_to=temp.joinpath('sub', 'dir', 'c')))

  # Build a tar of the whole `temp` directory.
  out_tar = (api.archive.package(temp).
             with_dir(temp).
             archive('archiving', out / 'output.tar.bz2'))

  # Build a zip for a subset.
  pkg = api.archive.package(temp)
  pkg = (pkg.
         with_file(pkg.root.joinpath('a')).
         with_file(pkg.root.joinpath('b')).
         with_dir(pkg.root.joinpath('sub')))
  out_zip = pkg.archive('archiving more', out / 'more.zip')

  # Zip the whole root
  all_zip = api.archive.package(temp).archive(
    'archiving all_zip',
    out / 'all_zip.zip'
  )

  # Build a tar.zst of the whole root as well.
  all_tzst = api.archive.package(temp).archive('archiving all_tzst',
                                               out / 'all_tzst.tzst')

  # Extract the packages.
  api.archive.extract('extract tar', out_tar, temp.joinpath('output1'))
  api.archive.extract('extract zip', out_zip, temp.joinpath('output2'))
  api.archive.extract('extract all_zip zip', all_zip, temp.joinpath('output3'))
  api.archive.extract('extract all_zip as zip', all_zip,
                      temp.joinpath('output4'), archive_type='zip')
  api.archive.extract('extract all_tzst', all_tzst, temp.joinpath('output5'))

  try:
    api.archive.extract('extract failure', out_zip, temp.joinpath('output3'))
  except api.step.StepFailure:
    pass

  # List extracted content.
  api.step('listing output1', ['find', temp.joinpath('output1')])
  api.step('listing output2', ['find', temp.joinpath('output2')])

  # Extract only a subset
  api.archive.extract('extract tar subset', out_tar,
                      temp.joinpath('output_sub'), include_files=['*/dir/*'])
  api.step('listing output_sub', ['find', temp.joinpath('output_sub')])


def GenTests(api):
  # only really care about the archiving and extract steps
  keep = (Filter().
          include_re('archiving.*').
          include_re('extract.*'))

  for platform in ('linux', 'win', 'mac'):
    yield (api.test(platform)
      + api.platform.name(platform)
      + api.step_data('extract failure', api.json.output({
        'extracted': {
          'filecount': 3,
          'bytes': 123456,
        },
        'skipped': {
          'filecount': 78,
          'bytes': 723456,
          'names': ['../bob', '/charlie', 'some/path/../../../../frank'],
        }
      }))
      + api.post_process(keep))
