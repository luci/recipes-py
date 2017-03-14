#!/usr/bin/env python
# Copyright 2017 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys

def main(argv):
  with open(argv[2], 'w') as f:
    f.write(argv[1])
  return 0

if __name__ == '__main__':
  sys.exit(main(sys.argv))
