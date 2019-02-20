# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'Fetch and update dependencies but take no other action.'


def add_arguments(parser):
  # fetch action is implied by recipes.py
  parser.set_defaults(func=(lambda _args: 0))
