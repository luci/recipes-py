# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Generate documentation from the recipes and modules in the current repo.

This can output as a protobuf of various forms (JSON, Text or binary), using the
`Doc` message in `recipe_engine/doc.proto`, or can emit gitiles-flavored
Markdown (either on stdout or written to the repo).
"""

def add_arguments(parser):
  doc_kinds = ('binarypb', 'jsonpb', 'textpb', 'gen', 'markdown')
  parser.add_argument(
      'recipe', nargs='?', help='Restrict documentation to this recipe')
  parser.add_argument(
      '--kind', default='jsonpb', choices=doc_kinds,
      help=(
        'Output this kind of documentation. `gen` will write the standard '
        'README.recipes.md file. All others output to stdout'))

  def _launch(args):
    from .cmd import main
    return main(args)
  parser.set_defaults(func=_launch)
