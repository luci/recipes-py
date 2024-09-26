# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.cv.api.config.v2 import config as cv_config_pb2
from PB.go.chromium.org.luci.milo.proto.projectconfig import project as milo_pb2

DEPS = [
    "recipe_engine/luci_config",
    "recipe_engine/buildbucket",
    "recipe_engine/path",
]

PROPERTIES = {}


def RunSteps(api):
  assert api.luci_config.commit_queue(local_dir=api.path.start_dir)
  assert api.luci_config.buildbucket()
  assert api.luci_config.milo()
  assert api.luci_config.scheduler()


def GenTests(api):
  yield (api.test("basic") + api.buildbucket.try_build(project="project") +
         api.luci_config.mock_local_config("project", "commit-queue.cfg",
                                           cv_config_pb2.Config()) +
         api.luci_config.mock_config(
             "project",
             "luci-milo.cfg",
             milo_pb2.Project(consoles=[milo_pb2.Console(id="global_ci")]),
         ))
