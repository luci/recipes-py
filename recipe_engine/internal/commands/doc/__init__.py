# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Generate documentation from the recipes and modules in the current repo.

This can output as a protobuf of various forms (JSON, Text or binary), using the
`Doc` message in `recipe_engine/doc.proto`, or can emit gitiles-flavored
Markdown (either on stdout or written to the repo).
"""

def add_arguments(parser):
  parser.add_argument(
      'recipe', nargs='?', help='Restrict documentation to this recipe')
  parser.add_argument(
      '--kind', default='gen',
      choices=('gen', 'binarypb', 'jsonpb', 'textpb', 'markdown'),
      help=(
        'Output this kind of documentation. `gen` (the default) will write the'
        ' standard README.recipes.md file. All others output to stdout'))
  parser.add_argument(
      '--check', action='store_true',
      help=(
        'Just check README.recipes.md to see if it is up to date, otherwise'
        ' print a diff and exit 1. Requires --kind=gen (i.e. the default).'
      )
  )

  def _launch(args):
    from .cmd import main

    if args.check and args.kind != 'gen':
      parser.error('--check must use --kind=gen')

    return main(args)
  parser.set_defaults(func=_launch, skip_dev=True)
