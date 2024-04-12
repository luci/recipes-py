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
#   * //workdir/tmp   - api.path.tmp_base_dir
#   * //workdir/cache - api.path.cache_dir
#   * //workdir/wd    - api.path.start_dir
#   * //workdir/logs  - Dumps of all the logdog streams emitted by the recipe
#     engine (and any child processes).
#
# This script is responsive to the following environment variables:
#   * LUCI_GRACE_PERIOD=<number> - Populates LUCI_CONTEXT['deadline']['grace_period']
#   * LUCI_SOFT_DEADLINE=<number> - Populates LUCI_CONTEXT['deadline']['soft_deadline']
#   * RECIPES_PY=<dir path> - Directory to the recipes-py directory, in case you
#     use a different one from chromium's. Default is to auto-detect chromium's
#     path.
#   * RECIPES_PY_SCRIPT=<file path> - The file path to the file recipes.py,
#     which are per-repository. Default is to use the one from the RECIPES_PY
#     dir.
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

RECIPES_PY="${RECIPES_PY:-$(realpath "$(git rev-parse --show-toplevel)")}"
RECIPES_PY_SCRIPT="${RECIPES_PY_SCRIPT:-${RECIPES_PY}/recipes.py}"
WD="${WD:-$RECIPES_PY/workdir}"

BINDIR="${RECIPES_PY}/misc/bindir"

echo "Clean workdir."
rm -rf "$WD"
mkdir -p "$WD/tmp" "$WD/cache" "$WD/wd" "$WD/luci_context"

cipd ensure -root "$BINDIR/butler" -ensure-file - <<EOF
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
    "grace_period": ${LUCI_GRACE_PERIOD:-30},
    "soft_deadline": ${LUCI_SOFT_DEADLINE:-0}
  }
}
EOF

EXTRA_ARGS=()

if [[ ! -z "$FAKE_BBAGENT_OUTFILE" ]]
then
  EXTRA_ARGS+=(--output "$FAKE_BBAGENT_OUTFILE")
fi

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
    "$BINDIR/butler/logdog_butler" -project local                 \
    -output directory,path="$WD/logs"                         \
    run -stdout=name=stdout -stderr=name=stderr               \
    -forward-stdin                                            \
    -chdir="$WD/wd"                                           \
    python3 -u "${RECIPES_PY_SCRIPT}" "$@" -vvv              \
    luciexe --build-proto-stream-jsonpb "${EXTRA_ARGS[@]}"
