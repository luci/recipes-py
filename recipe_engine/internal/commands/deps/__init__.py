# -*- coding: utf-8 -*-
# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Dumps all module dependencies for the given recipe or module.

If a module is given and --include-dependants is specified, this finds all
recipes which directly or indirectly depend on that module, and then calculates
the full dependency graph from that set of recipes.

Note that this only finds recipes in the current repo or one of this repo's
dependencies. Downstream repos which depend on this one may have recipes which
depend on the module queried.

The CLI output also indicates the both the claimed and effective Python3
conversion status of each item, according to the following legend:

    💀 - No python version satisfies stated constraints.
    ❌ - Only supports python2
    ✅ - Supports both python2 and python3
    🦄 - Only supports python3

The first column is the item's own claimed status, and the second column is
the computed effective status (i.e. minimum supported version among all of
its transitive dependencies).
"""

def add_arguments(parser):
  parser.add_argument(
      '--include-test-recipes',
      action='store_true',
      help=(
        'If set along with --include-dependants, will also include recipes '
        'under the examples/ and tests/ folders of recipe modules.'))

  parser.add_argument(
      '--include-dependants',
      action='store_true',
      help=(
        'If set, finds all recipes which transitively depend on the given '
        'module before walking all dependencies. No-op when specifying a '
        'recipe rather than a module.'))

  parser.add_argument(
      '--json-output',
      help=('Writes the Deps proto message as JSONPB to this `file`. '
            'If this is "-", then it writes to stdout.'))

  parser.add_argument(
      'recipe_or_module',
      help=('The fully-qualified recipe (`$repo::recipe`, '
            '`$repo::module:path/recipe`) or module (`$repo/module`).'
            'As a shorthand, the current repo can be indicated with an '
            'empty `$repo` (i.e. `::recipe`, `/module`). Use `*` to include'
            ' everything.'))

  def _launch(args):
    from .cmd import main
    return main(args)

  def _postprocess_func(error, args):
    rom = args.recipe_or_module
    if not (rom == '*' or '/' in rom or '::' in rom):
      error('recipe_or_module must be fully qualified (or `*`).')

  parser.set_defaults(
      func=_launch,
      postprocess_func=_postprocess_func,
      skip_dev=True,
  )
