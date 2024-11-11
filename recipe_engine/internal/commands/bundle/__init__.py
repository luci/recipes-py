# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Create a hermetically runnable recipe bundle (no git operations on startup).

Requires a git version >= 2.13+

This is done by packaging all the repos in RecipeDeps into a folder and then
generating an entrypoint script with `-O` override flags to this folder.

The general principle is that the input to bundle is:
  * The loaded RecipeDeps (derived from the main repo's recipes.cfg file). This
    is all the files on disk.
  * files tagged with the `recipes` gitattribute value (see
    `git help gitattributes`).
And the output is:
  * a runnable folder for the named repo

Some things that we'd want to do to make this better:
  * Allow this to fetch lazily from gitiles (no git clones)
    * will be necessary to support HUGE repos like chromium/src
  * Allow this to target a specific subset of runnable recipes (maybe)
    * prune down to ONLY the modules which are required to run those particular
      recipes.
    * this may be more trouble than it's worth

Included files

By default, bundle will include all recipes/ and recipe_modules/ files in your
repo, plus the `recipes.cfg` file, and excluding all json expectation files.

Recipe bundle also uses the standard `gitattributes` mechanism for tagging files
within the repo, and will also include these files when generating the bundle.
In particular, it looks for files tagged with the string `recipes`. As an
example, you could put this in a `.gitattributes` file in your repo:

```
*.py       recipes
*_test.py -recipes
```

That would include all .py files, but exclude all _test.py files. See the page
  `git help gitattributes`
For more information on how gitattributes work.
"""

import os


def add_arguments(parser):
  parser.add_argument(
      '--destination', default='./bundle',
      type=os.path.abspath,
      help='The directory of where to put the bundle (default: %(default)r).')

  def _launch(args):
    from .cmd import main
    return main(args)
  parser.set_defaults(func=_launch)
