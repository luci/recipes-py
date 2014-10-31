#!/usr/bin/python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides various tools for inspecting the layout of recipe configs."""

import argparse
import inspect
import os
import re
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from slave import recipe_loader
from slave import recipe_util


USAGE = """
%(prog)s <module_name>

Lists all configs defined for the given module, including extension modules.

%(prog)s <module_name>.<config_name>

Shows all the configs that would be applied (files, line numbers, and source)
if module_name.set_config(config_name) were called.
"""


RECIPE_MODULES = None
def init_recipe_modules():
  global RECIPE_MODULES
  RECIPE_MODULES = recipe_loader.load_recipe_modules(recipe_util.MODULE_DIRS())


def depth_first(start, children_func):
  """Return a depth-first traversal of a tree.

  Args:
    start: the root of the tree.
    children_func: function taking a node to its sequence of children.
  Returns:
    a list of nodes in depth-first order
  """
  seen = set()
  result = []

  def traversal(node):
    if node in seen:
      return
    seen.add(node)

    for i in children_func(node):
      traversal(i)
    result.append(node)

  traversal(start)
  return result


def transitive_includes(ctx, start):
  """Find all configs transitively included from start in the current context.
  """
  if start in ctx.CONFIG_ITEMS:
    return (
      ctx.CONFIG_ITEMS[i]
      for i in depth_first(start,
                           lambda config: ctx.CONFIG_ITEMS[config].INCLUDES))
  else:
    return []


def transitive_deps(start):
  """Find all dependences transitively included from a module."""
  return depth_first(start, lambda mod: getattr(RECIPE_MODULES, mod).DEPS)


def list_configs(module):
  """List all config names defined in a module (including extension modules).
  """
  mod = getattr(RECIPE_MODULES, module)
  ctx = mod.CONFIG_CTX
  for k in sorted(ctx.CONFIG_ITEMS.keys()):
    print k


def print_snippet(snippet):
  """Print the source file, line number, and source code of a config snippet.
  """
  sourcefile = inspect.getsourcefile(snippet.WRAPPED)
  (sourcelines, lineno) = inspect.getsourcelines(snippet.WRAPPED)
  print '%s:%s' % (sourcefile, lineno)
  print ''.join(sourcelines)


def dump_config(module, config):
  """Print detailed information about config in module and all configs it
  depends on."""
  for m in transitive_deps(module):
    mod = getattr(RECIPE_MODULES, m)
    ctx = mod.CONFIG_CTX
    if ctx:
      for v in transitive_includes(ctx, config):
        print_snippet(v)


def main(argv):
  init_recipe_modules()

  p = argparse.ArgumentParser(usage=USAGE)
  p.add_argument('module')
  options = p.parse_args()

  m = re.match(r'^(\w+)\.(\w+)$', options.module)
  if m:
    dump_config(m.group(1), m.group(2))
  else:
    list_configs(options.module)


if __name__ == '__main__':
  exit(main(sys.argv))
