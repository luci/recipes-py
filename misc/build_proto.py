#!/usr/bin/env vpython3
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys

from google.protobuf import json_format as jsonpb

sys.stdin.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(__file__))

sys.path.append(
    os.path.join(ROOT, '.recipe_deps', '_pb%d' % sys.version_info[0]))
from PB.go.chromium.org.luci.buildbucket.proto.build import Build

sys.stdout.buffer.write(
    jsonpb.Parse(sys.stdin.read(), Build()).SerializeToString())
