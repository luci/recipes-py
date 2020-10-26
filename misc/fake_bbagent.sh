#!/bin/bash
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

# This script emulates the LUCI User Code Contract (go/luci-user-code-contract,
# internal, sorry, but it's basically a lot of words that boil down to the
# responsibilities of the script below :)).
#
# Use this script like `fake_bbagent.sh < build.proto.jpb` where
# `build.proto.jpb` is a JSON encoded buildbucket.v2.Build message[1]. This
# script will transmute the JSON encoded message to a binary-encoded one (which
# is required by the code contract).
#
# This puts all the outputs from the executed recipe in the current git repo's
# //workdir directory:
#   * //workdir/tmp   - api.path['tmp_base']
#   * //workdir/cache - api.path['cache']
#   * //workdir/wd    - api.path['start_dir']
#   * //workdir/logs  - Dumps of all the logdog streams emitted by the recipe
#     engine (and any child processes).
#
# This script is responsive to the following environment variables:
#   * LUCI_GRACE_PERIOD=<number> - Populates LUCI_CONTEXT['deadline']['grace_period']
#
# Example:
#
#    ./misc/fake_bbagent.sh <<EOF & tail -F workdir/logs/stderr
#    {
#      "input": {
#        "properties": {
#          "recipe": "engine_tests/comprehensive_ui"
#        }
#      }
#    }
#    EOF
# [1]: https://chromium.googlesource.com/infra/luci/luci-go/+/master/buildbucket/proto/build.proto

RECIPES_PY="$(realpath "$(git rev-parse --show-toplevel)")"
WD="${WD:-$RECIPES_PY/workdir}"

echo "Clean workdir."
rm -rf "$WD"
mkdir -p "$WD/tmp" "$WD/cache" "$WD/wd" "$WD/luci_context"

cipd ensure -root "$WD/butler" -ensure-file - <<EOF
infra/tools/luci/logdog/butler/\${platform} latest
EOF

# Set up environmental predicates
unset LS_COLORS
export TMP="$WD/tmp"
export TEMP="$WD/tmp"
export TEMPDIR="$WD/tmp"
export TMPDIR="$WD/tmp"
export LOGDOG_NAMESPACE=u
export LOGDOG_COORDINATOR_HOST=logs.example.com
export LUCI_CONTEXT="$WD/luci_context/context.json"
cat > "$LUCI_CONTEXT" <<EOF
{
  "luciexe": {
    "cache_dir": "$WD/cache"
  },
  "deadline": {
    "grace_period": ${LUCI_GRACE_PERIOD:-30}
  }
}
EOF

# run `recipes.py fetch` to ensure protobufs are up to date; build_proto.py
# is cheeky and uses the compiled protos.
"$RECIPES_PY/recipes.py" fetch &> /dev/null

# Convert JSON -> binary PB
# Start a local logdog server.
# Project is "required" but its value doesn't matter.
# Output to the 'logs' subdir of workdir
# Attach "stdout" and "stderr" at their usual names.
# Set startdir to an empty dir.
# Set up a local fifo for butler to serve on.
# Actually run the recipes.
"$RECIPES_PY/misc/build_proto.py" | \
    "$WD/butler/logdog_butler" -project local                 \
    -output directory,path="$WD/logs"                         \
    run -stdout=name=stdout -stderr=name=stderr               \
    -forward-stdin                                            \
    -chdir="$WD/wd"                                           \
    python -u "$RECIPES_PY/recipes.py" "$@" -vvv              \
    luciexe --build-proto-stream-jsonpb
