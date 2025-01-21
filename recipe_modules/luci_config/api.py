# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
from typing import TypeVar

from google.protobuf import text_format as textpb
from PB.go.chromium.org.luci.buildbucket.proto import project_config as bb_pb2
from PB.go.chromium.org.luci.cv.api.config.v2 import config as cv_config_pb2
from PB.go.chromium.org.luci.milo.proto.projectconfig import project as milo_pb2
from PB.go.chromium.org.luci.scheduler.appengine.messages import config as scheduler_pb2
from PB.go.chromium.org.luci.config_service.proto import (
    config_service as config_service_pb2,)
from recipe_engine import config_types, recipe_api, recipe_test_api, step_data


class LuciConfigApi(recipe_api.RecipeApi):
  """Module for polling and parsing luci config files via the luci-config API.

  Depends on `prpc` binary being available in $PATH:
      https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc
  """

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._config_cache = {}

  def fetch_config_raw(
      self,
      config_name: str,
      project: str | None = None,
      local_dir: config_types.Path | None = None,
      allow_cache: bool = True,
  ) -> str:
    """Fetch and parse config file from the luci-config API as a proto.

    Since configs are unlikely to change significantly during a build and to
    simplify test data, results are cached.

    Args:
        config_name: The name of the config file to fetch, e.g.
            "commit-queue.cfg".
        project: The name of the LUCI project to fetch the config from; e.g.,
            "fuchsia". Defaults to the project that the current Buildbucket
            build is running in.
        local_dir: If specified, assumed to point to a local directory of files
            generated by lucicfg. The specified config file will be read from
            the corresponding local file rather than fetching it from the LUCI
            Config service.
        allow_cache: Allow retrieving from a cache if we've already retrieved
            this config before.
    """
    if not project:
      project = self.m.buildbucket.build.builder.project
      # Make this easier to use in recipe testing.
      if self._test_data.enabled:
        project = project or "project"
      assert project, "buildbucket input has no project set"

    key = (config_name, project, local_dir)

    if allow_cache and key in self._config_cache:
      return self._config_cache[key]

    if local_dir:
      self._config_cache[key] = self.m.file.read_text(
          f"read {project} {config_name}",
          local_dir / config_name,
      )
      return self._config_cache[key]

    with self.m.step.nest(f"fetch {project} {config_name}"):
      self._config_cache[key] = self._fetch_config_textproto(
          project,
          config_name,
      ).decode()
      return self._config_cache[key]

  MessageType = TypeVar('MessageType')

  def fetch_config(
      self,
      config_name: str,
      message_type: MessageType,
      project: str | None = None,
      local_dir: config_types.Path | None = None,
      allow_unknown_fields: bool = False,
      allow_cache: bool = True,
  ) -> MessageType:
    """Fetch and parse config file from the luci-config API as a proto.

    Since configs are unlikely to change significantly during a build and to
    simplify test data, results are cached.

    Args:
        config_name: The name of the config file to fetch, e.g.
            "commit-queue.cfg".
        message_type: The Python type corresponding to the config's protobuf
            message type.
        project: The name of the LUCI project to fetch the config from; e.g.
            "fuchsia". Defaults to the project that the current Buildbucket
            build is running in.
        local_dir: If specified, assumed to point to a local directory of files
            generated by lucicfg. The specified config file will be read from
            the corresponding local file rather than fetching it from the LUCI
            Config service.
        allow_unknown_fields: Whether to allow unknown fields, rather then
            erroring out on them. This is useful when reading config files for
            which the corresponding proto file that's been copied into the
            recipes repo may be out of date. This option should be used with
            care, as it strips potentially important information.
        allow_cache: Allow retrieving from a cache if we've already retrieved
            this config before.
    """
    text = self.fetch_config_raw(
        config_name=config_name,
        project=project,
        local_dir=local_dir,
        allow_cache=allow_cache,
    )

    cfg = message_type()
    textpb.Parse(
        text,
        cfg,
        allow_unknown_field=allow_unknown_fields,
    )
    return cfg

  def _fetch_config_textproto(self, project: str, config_name: str) -> bytes:
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

  def buildbucket(self, **kwargs) -> bb_pb2.BuildbucketCfg:
    return self.fetch_config("cr-buildbucket.cfg", bb_pb2.BuildbucketCfg,
                             **kwargs)

  def commit_queue(self, config_name: str | None = None,
                   **kwargs) -> cv_config_pb2.Config:
    # Support loading a CQ config file with a non-default name to support
    # projects that don't want a dedicated CQ instance but for which we
    # still want to know which tryjobs exist.
    config_name = config_name or "commit-queue.cfg"
    return self.fetch_config(config_name, cv_config_pb2.Config, **kwargs)

  def milo(self, **kwargs) -> milo_pb2.Project:
    return self.fetch_config("luci-milo.cfg", milo_pb2.Project, **kwargs)

  def scheduler(self, **kwargs) -> scheduler_pb2.ProjectConfig:
    return self.fetch_config("luci-scheduler.cfg", scheduler_pb2.ProjectConfig,
                             **kwargs)
