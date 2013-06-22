#!/usr/bin/env python
# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import print_function

import collections
import inspect
import sys

from slave import annotated_run
from slave import recipe_api

def trim_doc(docstring):
  """From PEP 257"""
  if not docstring:
    return ''
  # Convert tabs to spaces (following the normal Python rules)
  # and split into a list of lines:
  lines = docstring.expandtabs().splitlines()
  # Determine minimum indentation (first line doesn't count):
  indent = sys.maxint
  for line in lines[1:]:
    stripped = line.lstrip()
    if stripped:
      indent = min(indent, len(line) - len(stripped))
  # Remove indentation (first line is special):
  trimmed = [lines[0].strip()]
  if indent < sys.maxint:
    for line in lines[1:]:
      trimmed.append(line[indent:].rstrip())
  # Strip off trailing and leading blank lines:
  while trimmed and not trimmed[-1]:
    trimmed.pop()
  while trimmed and not trimmed[0]:
    trimmed.pop(0)
  return trimmed

def member_iter(obj):
  for name in sorted(dir(obj)):
    if name[0] == '_' and name != '__call__':
      continue
    val = getattr(obj, name)
    if(not callable(val) and
       not inspect.ismodule(val)):
      if hasattr(obj.__class__, name):
        realobj = getattr(obj.__class__, name)
        if isinstance(realobj, property):
          yield name, realobj
      continue
    yield name, val

def map_to_cool_name(typ):
  if typ is collections.Mapping:
    return 'Mapping'
  return typ

def p(indent_lvl, *args, **kwargs):
  sys.stdout.write('  '*indent_lvl)
  print(*args, **kwargs)

def pmethod(indent_lvl, name, obj):
  if isinstance(obj, property):
    name = '@'+name
  p(indent_lvl, name, '', end='')
  if obj.__doc__:
    lines = trim_doc(obj.__doc__)
    p(0, '--', lines[0])
  else:
    p(0)

def main():
  common_methods = set(k for k, v in member_iter(recipe_api.RecipeApi))
  p(0, 'Common Methods:')
  for method in sorted(common_methods):
    pmethod(1, method, getattr(recipe_api.RecipeApi, method))
  RECIPE_MODULES = recipe_api.load_recipe_modules(annotated_run.MOD_DIRS)
  for mod_name, mod in member_iter(RECIPE_MODULES):
    p(0)
    p(0, "(%s) -- %s" % (mod_name, mod.__path__[0]))
    inst = recipe_api.CreateRecipeApi([mod_name], annotated_run.MOD_DIRS,
                                      mocks={'path': {}}, properties={},
                                      step_history={})
    if mod.DEPS:
      p(1, 'DEPS:', list(mod.DEPS))

    subinst = getattr(inst, mod_name)
    bases = set(subinst.__class__.__bases__)
    base_fns = set()
    for base in bases:
      for name, _ in inspect.getmembers(base):
        base_fns.add(name)
    for cool_base in bases - set((recipe_api.RecipeApi,)):
      p(1, 'behaves like %s' % map_to_cool_name(cool_base))

    if mod.API.__doc__:
      for line in trim_doc(mod.API.__doc__):
        p(2, '"', line)

    for fn_name, obj in member_iter(subinst):
      if fn_name in base_fns:
        continue
      pmethod(1, fn_name, obj)


if __name__ == '__main__':
  main()
