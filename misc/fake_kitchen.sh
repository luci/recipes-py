#!/bin/bash
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

# This script emulates the LUCI User Code Contract (go/luci-user-code-contract,
# internal, sorry, but it's basically a lot of words that boil down to the
# responsibilities of the script below :)).
#
# Use this script like `fake_kitchen.py < build.proto.pb` where `build.proto.pb`
# is a binary encoded buildbucket.v2.Build message[1].
#
# This puts all the outputs from the executed recipe in the current git repo's
# //workdir directory:
#   * //workdir/tmp   - api.path['tmp_base']
#   * //workdir/cache - api.path['cache']
#   * //workdir/wd    - api.path['start_dir']
#   * //workdir/logs  - Dumps of all the logdog streams emitted by the recipe
#     engine (and any child processes).
#
# This script requires the `logdog_butler` tool[2] in your $PATH. If you have an
# 'infra' checkout, you can get this by doing:
#   * eval `//infra/go/env.py`
#   * go install go.chromium.org/luci/logdog/client/cmd/logdog_butler
#
# [1]: https://chromium.googlesource.com/infra/luci/luci-go/+/master/buildbucket/proto/build.proto
# [2]: https://chromium.googlesource.com/infra/luci/luci-go/+/refs/heads/master/logdog/client/cmd/logdog_butler

ROOT="$(realpath $(git rev-parse --show-toplevel))"
WD="$ROOT/workdir"

echo "Clean workdir."
rm -rf "$WD"
mkdir -p "$WD/tmp" "$WD/cache" "$WD/wd"

# Set up environmental predicates
# Start a local logdog server.
# Project is "required" but its value doesn't matter.
# Output to the 'logs' subdir of workdir
# Attach "stdout" and "stderr" at their usual names.
# Set startdir to an empty dir.
# Actaully run the recipes.
TMP="$WD/tmp" LUCI_CACHE_DIR="$WD/cache" LOGDOG_NAMESPACE=u \
  logdog_butler -project local                              \
  -output directory,path="$WD/logs"                         \
  run -stdout=name=stdout -stderr=name=stderr               \
  -chdir="$WD/wd"                                           \
  python "$ROOT/recipes.py" -vvv run_build "$@"
