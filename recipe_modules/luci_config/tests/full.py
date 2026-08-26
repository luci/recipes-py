# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.cv.api.config.v2 import config as cv_config_pb2
from PB.go.chromium.org.luci.milo.proto.projectconfig import project as milo_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    luci_config,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  luci_config: luci_config.API
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  luci_config: luci_config.TEST_API


def RunSteps(api: DEPS):
  assert api.luci_config.commit_queue(local_dir=api.path.start_dir)
  assert api.luci_config.buildbucket()
  assert api.luci_config.milo()
  assert api.luci_config.scheduler()
  assert api.luci_config.scheduler()  # To test cache.

  api.luci_config.clear_cache()
  assert api.luci_config.commit_queue(local_dir=api.path.start_dir)
  assert api.luci_config.milo()


def GenTests(api: TEST_DEPS):
  yield api.test(
      "basic",
      api.buildbucket.try_build(project="project"),
      api.luci_config.mock_local_config("project", "commit-queue.cfg",
                                        cv_config_pb2.Config()),
      api.luci_config.mock_local_config("project", "commit-queue.cfg",
                                        cv_config_pb2.Config(),
                                        iteration=2),
      api.luci_config.mock_config(
          "project",
          "luci-milo.cfg",
          milo_pb2.Project(consoles=[milo_pb2.Console(id="global_ci")]),
      ),
      api.luci_config.mock_config(
          "project",
          "luci-milo.cfg",
          milo_pb2.Project(consoles=[milo_pb2.Console(id="global_ci_2")]),
          iteration=2,
      ),
  )

  yield api.test(
      "signed_url",
      api.buildbucket.try_build(project="project"),
      api.luci_config.mock_local_config("project", "commit-queue.cfg",
                                        cv_config_pb2.Config()),
      api.luci_config.mock_local_config(
          "project", "commit-queue.cfg", cv_config_pb2.Config(), iteration=2),
      api.luci_config.mock_config_signed_url(
          "project",
          "luci-milo.cfg",
          milo_pb2.Project(consoles=[milo_pb2.Console(id="global_ci")]),
      ),
      api.luci_config.mock_config_signed_url(
          "project",
          "luci-milo.cfg",
          milo_pb2.Project(consoles=[milo_pb2.Console(id="global_ci_2")]),
          iteration=2,
      ),
  )
