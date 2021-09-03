#!/usr/bin/env python
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Simple script for creating symbolic links for an arbitrary number of path pairs."""

import argparse
import errno
import json
import os
import sys


def main(args):
  parser = argparse.ArgumentParser(description='Create symlinks')
  parser.add_argument("--link-json",
                      help="Simple JSON mapping of a source to a linkname",
                      required=True)
  args = parser.parse_args()
  with open(args.link_json, 'r') as f:
    links = json.load(f)

  made_dirs = set()
  def make_parent_dirs(path):
    path = os.path.dirname(path)
    if path in made_dirs:
      return
    try:
      os.makedirs(path, 0o777)
    except OSError as ex:
      if ex.errno != errno.EEXIST:
        raise
    while path and path not in made_dirs:
      made_dirs.add(path)
      path = os.path.dirname(path)

  for target, linknames in links.items():
    for linkname in linknames:
      make_parent_dirs(linkname)
      os.symlink(target, linkname)

if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
