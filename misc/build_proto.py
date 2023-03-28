#!/usr/bin/env vpython
# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys

from google.protobuf import json_format as jsonpb

ROOT = os.path.dirname(os.path.dirname(__file__))

sys.path.append(
    os.path.join(ROOT, '.recipe_deps', '_pb%d' % sys.version_info[0]))
from PB.go.chromium.org.luci.buildbucket.proto.build import Build

sys.stdout.write(jsonpb.Parse(sys.stdin.read(), Build()).SerializeToString())
