# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation
from recipe_engine.config_types import Path, ResolvedBasePath

DEPS = [
    'path',
    'platform',
]


def RunSteps(api):
  if api.platform.is_win:
    arbitrary = api.path.cast_to_path(r'c:\some\random/path')
    assert arbitrary.base == ResolvedBasePath(r'c:'), f'"{arbitrary.base!r}"'
    assert arbitrary.pieces == ('some', 'random',
                                'path'), f'{arbitrary.pieces!r}'
    assert str(arbitrary) == r'c:\some\random\path'

    arbitrary2 = api.path.cast_to_path(r'c:\\\\\hey/there')
    assert arbitrary2 == Path(ResolvedBasePath(r'c:'), 'hey', 'there')

    try:
      # non-absolute paths fail
      api.path.cast_to_path(r'hey\there')
      assert False  # pragma: no cover
    except ValueError:
      pass

    assert api.path.isfile(r'd:\legit\file')

  else:
    arbitrary = api.path.cast_to_path('/some/random/path')
    assert arbitrary.base == ResolvedBasePath(''), f'"{arbitrary.base!r}"'
    assert arbitrary.pieces == ('some', 'random',
                                'path'), f'{arbitrary.pieces!r}'
    assert str(arbitrary) == '/some/random/path'

    try:
      # non-absolute paths fail
      api.path.cast_to_path(r'cool/beans')
      assert False  # pragma: no cover
    except ValueError:
      pass

    assert api.path.isdir(r'/legit/dir')
    assert api.path.isdir(r'/legit/dir/etc')


def GenTests(api):
  yield api.test(
      'win',
      api.platform.name('win'),
      api.path.exists(api.path.cast_to_path(r'd:\legit\file')),
      api.post_process(DropExpectation),
  )

  base = api.path.cast_to_path('/legit/dir')

  yield api.test(
      'linux',
      api.platform.name('linux'),
      api.path.dirs_exist(base.join('etc')),
      api.post_process(DropExpectation),
  )
