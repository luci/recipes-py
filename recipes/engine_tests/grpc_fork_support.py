# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Asserts that gRPC fork support is disabled in the recipe engine.

The recipe engine spawns a subprocess (fork()+exec with close_fds=True) for
every step. On Linux the grpcio wheel is compiled with fork support enabled by
default (GRPC_ENABLE_FORK_SUPPORT_DEFAULT=true), so gRPC C-core registers
pthread_atfork handlers. If a fork() happens while other threads are calling
into gRPC, the prefork handler skips (logging "Other threads are currently
calling into gRPC, skipping fork() handlers"), so the postfork child never
resets the polling engine; when the child then closes inherited fds before
exec, epoll_wait() hits EBADF and aborts the child with SIGABRT (exit -6).

recipe_engine/main.py sets GRPC_ENABLE_FORK_SUPPORT=0 before anything imports
grpc, which makes C-core latch fork support as disabled (no atfork handlers).

This recipe reads the value via ENV_PROPERTIES and fails if it is not "0". It is
run for real (through main.py) by RunSmokeTest.test_grpc_fork_support in
unittests/run_test.py, which is what actually guards the main.py fix. See
b/537839459.
"""

from __future__ import annotations

from dataclasses import dataclass

from recipe_engine.post_process import DropExpectation
from recipe_engine.recipe_api import RecipeScriptApi, StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import properties

from PB.recipes.recipe_engine.engine_tests import grpc_fork_support


ENV_PROPERTIES = grpc_fork_support.EnvProperties


@dataclass
class DEPS(RecipeScriptApi):
  pass


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.API


def RunSteps(api: DEPS, env_properties):
  if env_properties.GRPC_ENABLE_FORK_SUPPORT != '0':
    raise StepFailure(
        'GRPC_ENABLE_FORK_SUPPORT is %r, expected "0". recipe_engine/main.py '
        'must set it to "0" before grpc is imported to disable gRPC C-core '
        'fork support. See b/537839459.'
        % (env_properties.GRPC_ENABLE_FORK_SUPPORT,))


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.properties.environ(
          ENV_PROPERTIES(GRPC_ENABLE_FORK_SUPPORT="0")
      ),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'fail',
      api.post_process(DropExpectation),
      status='FAILURE',
  )
