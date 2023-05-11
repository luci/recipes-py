#!/usr/bin/env python3
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys

def main(argv):
  with open(argv[2], 'w', encoding='utf-8') as output:
    output.write(argv[1])
  return 0

if __name__ == '__main__':
  sys.exit(main(sys.argv))
