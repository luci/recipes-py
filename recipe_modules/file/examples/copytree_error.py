# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation, StepFailure

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    "file",
    "path",
]


def RunSteps(api):
  # Ensure a api.file.Error if the source path does not exist
  try:
    api.file.copytree('dir not found - raise error',
                      api.path['start_dir'].join('not_there'),
                      api.path['start_dir'].join('some_path'))
    assert False, "never reached"  # pragma: no cover
  except api.file.Error as e:
    assert e.errno_name == 'ENOENT'

  # Ensure no error is raised with the `fail_silently` flag
  api.file.copytree(
      'dir not found - fail silently',
      api.path['start_dir'].join('not_there'),
      api.path['start_dir'].join('some_path'),
      skip_empty_source=True)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('dir not found - raise error', api.file.errno('ENOENT')),
      api.step_data('dir not found - fail silently', api.file.errno('ENOENT')),
      api.post_process(StepFailure, 'dir not found - fail silently'),
      api.post_process(DropExpectation))
