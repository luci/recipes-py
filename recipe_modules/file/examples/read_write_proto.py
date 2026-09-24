# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Iterator
from recipe_engine import recipe_test_api

from PB.recipe_modules.recipe_engine.file.examples.read_write_proto import SomeMessage

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    file,
    path,
    proto,
)


@dataclass
class DEPS(RecipeScriptApi):
  file: file.API
  path: path.API
  proto: proto.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  file: file.TEST_API


def RunSteps(api: DEPS) -> None:
  msg = SomeMessage(fields=['abc', 'def'])

  dest = api.path.start_dir / 'message.textproto'
  api.file.write_proto('write_proto', dest, msg, 'TEXTPB')

  read_msg = api.file.read_proto(
      'read_proto',
      dest,
      SomeMessage,
      'TEXTPB',
      test_proto=msg)

  assert read_msg == msg, (read_msg, msg)

  # read_proto call without test_proto, for test coverage.
  read_msg_again = api.file.read_proto(
      'read_proto_again',
      dest,
      SomeMessage,
      'TEXTPB')


def GenTests(api: TEST_DEPS) -> Iterator[recipe_test_api.TestData]:
  yield api.test('basic')
  read_proto_data = api.file.read_proto(SomeMessage(fields=['abc', 'def']))
  yield (api.test('override_step_data')
         + api.override_step_data('read_proto_again', read_proto_data))
