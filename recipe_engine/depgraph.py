# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import print_function

import sys

from . import loader


_GRAPH_HEADER = """strict digraph {
  concentrate = true;
  ranksep = 2;
  nodesep = 0.25;
"""

_GRAPH_FOOTER = """}
"""


def main(universe, ignore_packages, stdout):
  packages = {}
  module_to_package = {}
  edges = []
  for package, modpath in universe.loop_over_recipe_modules():
    mod = universe.load(loader.PathDependency(
        modpath, modpath, package, universe))
    for dep in mod.LOADED_DEPS:
      edges.append((mod.NAME, dep))
    packages.setdefault(package.name, []).append(mod.NAME)
    module_to_package[mod.NAME] = package.name

  print(_GRAPH_HEADER, file=stdout)
  for edge in edges:
    if (module_to_package[edge[0]] in ignore_packages or
        module_to_package[edge[1]] in ignore_packages):
      continue
    print('  %s -> %s' % (edge[0], edge[1]), file=stdout)
  for package, modules in packages.iteritems():
    if package in ignore_packages:
      continue
    # The "cluster_" prefix has magic meaning for graphviz and makes it
    # draw a box around the subgraph.
    print('  subgraph "cluster_%s" { label="%s"; %s; }' % (
              package, package, '; '.join(modules)), file=stdout)
  print(_GRAPH_FOOTER, file=stdout)
