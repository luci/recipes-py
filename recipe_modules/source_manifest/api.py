# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api
from PB.go.chromium.org.luci.common.proto.srcman.manifest import Manifest

from google.protobuf import json_format

"""This module allows you to upload 'Source Manifests' for your job.

These manifest allow other systems, like Milo, to understand what sources your
recipe has checked out, from repos, and at which revisions. This information can
then be used for things like the console view UI, generating blamelists between
two recipe executions, or aiding in debugging by giving additional insight into
the task.

The Source Manifest data is described by the proto:
  https://chromium.googlesource.com/infra/luci/luci-go/+/master/common/proto/srcman/manifest.proto

Every source_manifest has a name, which indicates what collection of sources it
represents. Examples of names might be:
  * main_checkout
  * bisect/deadbeef
  * patched_checkout

The requirement is that the name is a valid LogDog stream name (meaning
essentially letters, numbers, underscores and slashes). The prefix 'luci/' is
reserved.
"""

class SourceManfiestApi(recipe_api.RecipeApi):
  source_client = recipe_api.RequireClient('source_manifest')

  def set_json_manifest(self, name, data):
    """Uploads a source manifest with the given name.

    NOTE: Due to current implementation restrictions, this method may only be
    called after some step has been run from the recipe. Calling this before
    running any steps is invalid and will fail. We hope to lift this restriction
    sometime after we don't need to support buildbot any more.

    # TODO(iannucci): remove this restriction.

    Args:
      * name (str) - the name of the manifest. These names must be valid LogDog
        stream names, and must be unique within a recipe run. e.g.
        * "main_checkout"
        * "bisect/deadbeef"
      * data (dict) - the JSONPB representation of the source_manifest.proto
        Manifest message.
    """
    pb = Manifest()
    json_format.ParseDict(data, pb, ignore_unknown_fields=True)
    self.source_client.upload_manifest(name, pb)
