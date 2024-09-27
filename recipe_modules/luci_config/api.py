# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64

from google.protobuf import text_format as textpb

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import project_config as bb_pb2
from PB.go.chromium.org.luci.cv.api.config.v2 import config as cv_config_pb2
from PB.go.chromium.org.luci.milo.proto.projectconfig import project as milo_pb2
from PB.go.chromium.org.luci.scheduler.appengine.messages import config as scheduler_pb2
from PB.go.chromium.org.luci.config_service.proto import (
    config_service as config_service_pb2,)


class LuciConfigApi(recipe_api.RecipeApi):
  """Module for polling and parsing luci config files via the luci-config API.

  Depends on `prpc` binary being available in $PATH:
      https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc
  """

  def fetch_config_raw(
      self,
      config_name,
      project=None,
      local_dir=None,
  ):
    """Fetch and parse config file from the luci-config API as a proto.

    Args:
        config_name (str): The name of the config file to fetch, e.g.
            "commit-queue.cfg".
        project (str): The name of the LUCI project to fetch the config
            from; e.g. "fuchsia". Defaults to the project that the
            current Buildbucket build is running in.
        local_dir (Path): If specified, assumed to point to a local
            directory of files generated by lucicfg. The specified config
            file will be read from the corresponding local file rather
            than fetching it from the LUCI Config service.
    """
    if not project:
      project = self.m.buildbucket.build.builder.project
      # Make this easier to use in recipe testing.
      if self._test_data.enabled:
        project = project or "project"
      assert project, "buildbucket input has no project set"

    if local_dir:
      return self.m.file.read_text(f"read {project} {config_name}",
                                   local_dir / config_name)

    with self.m.step.nest(f"fetch {project} {config_name}"):
      return self._fetch_config_textproto(project, config_name).decode()

  def fetch_config(
      self,
      config_name,
      message_type,
      project=None,
      local_dir=None,
      allow_unknown_fields=False,
  ):
    """Fetch and parse config file from the luci-config API as a proto.

    Args:
        config_name (str): The name of the config file to fetch, e.g.
            "commit-queue.cfg".
        message_type (type): The Python type corresponding to the
            config's protobuf message type.
        project (str): The name of the LUCI project to fetch the config
            from; e.g. "fuchsia". Defaults to the project that the
            current Buildbucket build is running in.
        local_dir (Path): If specified, assumed to point to a local
            directory of files generated by lucicfg. The specified config
            file will be read from the corresponding local file rather
            than fetching it from the LUCI Config service.
        allow_unknown_fields (bool): Whether to allow unknown fields, rather
            than erroring out on them. This is useful when reading config
            files for which the corresponding proto file that's been copied
            into the recipes repo may be out of date. This option should be
            used with care, as it strips potentially important information.
    """
    text = self.fetch_config_raw(
        config_name=config_name,
        project=project,
        local_dir=local_dir,
    )

    cfg = message_type()
    textpb.Parse(
        text,
        cfg,
        allow_unknown_field=allow_unknown_fields,
    )
    return cfg

  def _fetch_config_textproto(self, project, config_name):
    req = config_service_pb2.GetConfigRequest(
        config_set=f"projects/{project}", path=config_name)
    resp = self.m.step(
        name="get",
        cmd=[
            "prpc",
            "call",
            "-format=json",
            "config.luci.app",
            "config.service.v2.Configs.GetConfig",
        ],
        stdin=self.m.proto.input(req, "JSONPB"),
        stdout=self.m.proto.output(config_service_pb2.Config, "JSONPB"),
        infra_step=True,
        step_test_data=lambda: self.m.proto.test_api.output_stream(
            config_service_pb2.Config(raw_content=b"")),
    ).stdout

    # Responses for extremely large config files will have the `signed_url`
    # populated instead of `raw_content` and the file must be fetched using
    # the signed URL. At time of writing this code is not used to fetch
    # config files of that size, so support for signed URLs is not required.
    if resp.WhichOneof("content") != "raw_content":
      raise Exception(  # pragma: no cover
          f"{config_name} can only be fetched by signed URL. "
          "TODO(you): Implemented signed URL fetching :)")

    return resp.raw_content

  def buildbucket(self, **kwargs):
    return self.fetch_config("cr-buildbucket.cfg", bb_pb2.BuildbucketCfg,
                             **kwargs)

  def commit_queue(self, config_name=None, **kwargs):
    # Support loading a CQ config file with a non-default name to support
    # projects that don't want a dedicated CQ instance but for which we
    # still want to know which tryjobs exist.
    config_name = config_name or "commit-queue.cfg"
    return self.fetch_config(config_name, cv_config_pb2.Config, **kwargs)

  def milo(self, **kwargs):
    return self.fetch_config("luci-milo.cfg", milo_pb2.Project, **kwargs)

  def scheduler(self, **kwargs):
    return self.fetch_config("luci-scheduler.cfg", scheduler_pb2.ProjectConfig,
                             **kwargs)