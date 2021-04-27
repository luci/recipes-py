# -*- coding: utf-8 -*-
# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Dumps all module dependencies for the given recipe or module.

If a module is given, this finds all recipes which directly or indirectly depend
on that module, and then calculates the full dependency graph from that set of
recipes.

Note that this only finds recipes in the current repo or one of this repo's
dependencies. Downstream repos which depend on this one may have recipes which
depend on the module queried.

The CLI output also indicates the Python3 conversion status of each item,
according to the following legend:

    ❌ - Only supports python2
    ✅ - Supports both python2 and python3
    🦄 - Only supports python3
"""

def add_arguments(parser):
  parser.add_argument(
      '--include-test-recipes',
      action='store_true',
      help=(
        'If set, includes recipes under the examples/ and tests/ folders '
        'of recipe modules.'))

  parser.add_argument(
      '--json-output',
      help=('Writes the Deps proto message as JSONPB to this `file`. '
            'If this is "-", then it writes to stdout.'))

  parser.add_argument(
      'recipe_or_module',
      help=('The fully-qualified recipe (`$repo::recipe`, '
            '`$repo::module:path/recipe`) or module (`$repo/module`).'
            'As a shorthand, the current repo can be indicated with an '
            'empty `$repo` (i.e. `::recipe`, `/module`)'))

  def _launch(args):
    from .cmd import main
    return main(args)

  def _postprocess_func(error, args):
    if '/' not in args.recipe_or_module and '::' not in args.recipe_or_module:
      error('recipe_or_module must be fully qualified.')

  parser.set_defaults(
      func=_launch,
      postprocess_func=_postprocess_func,
  )
