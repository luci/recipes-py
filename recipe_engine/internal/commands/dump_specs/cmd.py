# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from google.protobuf import json_format as jsonpb

from PB.recipe_engine.recipes_cfg import DepRepoSpecs


def main(args):
  specs = DepRepoSpecs()

  for name, dep in args.recipe_deps.repos.items():
    specs.repo_specs[name].CopyFrom(dep.recipes_cfg_pb2)

  print jsonpb.MessageToJson(
      specs, preserving_proto_field_name=True, indent=2, sort_keys=True)

  return 0
